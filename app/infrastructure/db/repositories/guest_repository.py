"""Misafir (CRM) veri erisimi.

Sifreli alanda arama
--------------------
Kimlik/pasaport numarasi :class:`~app.infrastructure.db.types.EncryptedString`
ile saklanir ve Fernet her yazmada farkli sifreli metin uretir. Bu yuzden
``WHERE identity_number = ?`` **hicbir zaman** eslesmez. Esitlik aramasi
yalnizca deterministik kor indeks (:func:`~app.infrastructure.db.types
.blind_index`) uzerinden yapilabilir; bu modul o donusumu tek noktada yapar
ki cagiran taraf tuzaga dusmesin.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import ColumnElement, func, or_, select

from app.domain.value_objects import to_decimal
from app.infrastructure.db.models.billing import Folio
from app.infrastructure.db.models.guests import Guest
from app.infrastructure.db.models.reservations import Reservation, ReservationRoom, Stay
from app.infrastructure.db.repositories.base import BaseRepository
from app.infrastructure.db.types import blind_index


class GuestRepository(BaseRepository[Guest]):
    """Misafir profilleri, kimlik aramasi ve CRM ozetleri."""

    model = Guest
    entity_label = "Misafir"

    # ------------------------------------------------------------------
    #  Arama
    # ------------------------------------------------------------------
    def search(self, query: str, *, limit: int = 50) -> list[Guest]:
        """Ad, soyad, e-posta ve telefon uzerinde serbest metin aramasi.

        Ad ve soyadin birlestirilmis hali de aranir; boylece "Deniz Yildizli"
        yazan kullanici sonucu bulur (tek tek alanlarda bu ifade gecmez).

        Bos veya yalnizca bosluktan olusan sorgu **bos liste** dondurur:
        aksi halde tum misafir tabani cekilir ve arayuz kilitlenirdi.

        Telefon aramasi ham metin uzerinde yapilir; kullanici bosluklu
        yazarsa ("555 000") kayitla eslesmeyebilir. Normalizasyon servis
        katmaninin isidir - burada veriyi degistirmeyiz.
        """
        cleaned = query.strip()
        if not cleaned:
            return []
        pattern = f"%{cleaned}%"
        full_name = Guest.first_name + " " + Guest.last_name
        stmt = (
            select(Guest)
            .where(
                Guest.is_deleted.is_(False),
                or_(
                    Guest.first_name.ilike(pattern),
                    Guest.last_name.ilike(pattern),
                    full_name.ilike(pattern),
                    Guest.email.ilike(pattern),
                    Guest.phone.ilike(pattern),
                    Guest.mobile.ilike(pattern),
                ),
            )
            .order_by(Guest.last_name, Guest.first_name, Guest.id)
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def find_by_identity(self, number: str) -> Guest | None:
        """Kimlik/pasaport numarasindan misafiri bulur.

        Numara once kor indekse cevrilir; ham numara **hicbir zaman** SQL
        metnine girmez, dolayisiyla sorgu gunluklerinde de gorunmez.
        ``identity_index`` benzersiz oldugu icin en fazla tek kayit doner.
        """
        cleaned = number.strip() if number else ""
        if not cleaned:
            return None
        index = blind_index(cleaned)
        if index is None:
            return None
        stmt = select(Guest).where(
            Guest.identity_index == index,
            Guest.is_deleted.is_(False),
        )
        return self.session.scalars(stmt).one_or_none()

    def find_duplicates(self, guest: Guest) -> list[Guest]:
        """Verilen misafirle ayni kisi olmasi muhtemel kayitlari dondurur.

        Iki olcut kullanilir:

        * Ayni ad + soyad + dogum tarihi,
        * Ayni e-posta adresi.

        Kimlik numarasi olcut degildir; onun icin :meth:`find_by_identity`
        vardir ve zaten benzersizlik kisiti bulunur.

        ``None`` degerler olcut olarak kullanilmaz: dogum tarihi girilmemis
        iki farkli "Ali Yilmaz" kaydini birlestirmeye calismak, gercekten
        farkli iki misafiri birbirine karistirmak demektir. Ayni gerekce ile
        bos e-posta eslesme uretmez.

        Kaydin kendisi (id atanmissa) sonuctan cikarilir.
        """
        # Tur ipucu acikca verilir: ilk eleman bilesik (``&``) bir ifade,
        # ikincisi tekil bir esitliktir; annotate edilmezse liste turu ilk
        # elemandan daraltilir ve ikinci ``append`` tur hatasi uretir.
        criteria: list[ColumnElement[bool]] = []
        if guest.birth_date is not None:
            criteria.append(
                (Guest.first_name == guest.first_name)
                & (Guest.last_name == guest.last_name)
                & (Guest.birth_date == guest.birth_date)
            )
        if guest.email:
            criteria.append(Guest.email == guest.email)
        if not criteria:
            return []

        stmt = select(Guest).where(Guest.is_deleted.is_(False), or_(*criteria))
        if guest.id is not None:
            stmt = stmt.where(Guest.id != guest.id)
        return list(self.session.scalars(stmt.order_by(Guest.id)).all())

    # ------------------------------------------------------------------
    #  CRM ozetleri
    # ------------------------------------------------------------------
    def update_crm_summary(self, guest_id: int) -> Guest:
        """Misafirin denormalize CRM ozetlerini yeniden hesaplar.

        ``total_stays``, ``total_nights``, ``total_revenue`` ve ilk/son
        konaklama tarihleri :class:`Stay` ve :class:`Folio` tablolarindan
        yeniden turetilir. Alanlar denormalize tutulur cunku misafir listesi
        ekrani binlerce satirda bu degerleri gosterir; her satirda toplam
        hesaplamak listeyi kullanilmaz hale getirirdi. Bunun bedeli, ozetin
        eskiyebilmesidir - bu yontem "tek dogruluk kaynagindan yeniden kur"
        islemidir ve konaklama kapandiktan sonra cagrilmalidir.

        Gece sayisi hesabi
        ------------------
        Cikis yapmis konaklamalarda **fiili** tarihler kullanilir; misafir
        halen oteldeyse plan tarihleri esas alinir. Erken cikis yapan bir
        misafirin planlanan gecesi uzerinden sadakat puani kazanmasi yanlis
        olurdu.

        Ciro hesabi
        -----------
        Folyolar hem dogrudan misafire bagli olanlar hem de misafirin asil
        misafir oldugu rezervasyonlara bagli olanlar uzerinden toplanir;
        ``OR`` tek sorguda uygulandigi icin ayni folyo iki kez sayilmaz.
        Toplanan alan ``total_charges``'tir: ciro tahsil edilen degil,
        **islenen** tutardir.
        """
        guest = self.get_or_404(guest_id)

        stay_rows = self.session.execute(
            select(
                Stay.actual_check_in,
                Stay.actual_check_out,
                ReservationRoom.check_out_date,
            )
            .join(ReservationRoom, Stay.reservation_room_id == ReservationRoom.id)
            .join(Reservation, ReservationRoom.reservation_id == Reservation.id)
            .where(
                Reservation.primary_guest_id == guest_id,
                Reservation.is_deleted.is_(False),
                ReservationRoom.is_cancelled.is_(False),
            )
        ).all()

        total_nights = 0
        first_day: date | None = None
        last_day: date | None = None
        for actual_in, actual_out, planned_out in stay_rows:
            arrival = actual_in.date()
            departure = actual_out.date() if actual_out is not None else planned_out
            total_nights += max((departure - arrival).days, 0)
            first_day = arrival if first_day is None else min(first_day, arrival)
            last_day = departure if last_day is None else max(last_day, departure)

        revenue = self.session.scalar(
            select(func.coalesce(func.sum(Folio.total_charges), 0)).where(
                or_(
                    Folio.guest_id == guest_id,
                    Folio.reservation_id.in_(
                        select(Reservation.id).where(
                            Reservation.primary_guest_id == guest_id,
                            Reservation.is_deleted.is_(False),
                        )
                    ),
                )
            )
        )

        guest.total_stays = len(stay_rows)
        guest.total_nights = total_nights
        guest.total_revenue = to_decimal(revenue if revenue is not None else Decimal("0.00"))
        guest.first_stay_date = first_day
        guest.last_stay_date = last_day
        self.session.flush()
        return guest


__all__ = ["GuestRepository"]
