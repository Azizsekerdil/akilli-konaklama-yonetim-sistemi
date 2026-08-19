"""Rezervasyon veri erisimi - musaitlik hesabinin veri kaynagi.

Bu modul sistemin en kritik sorgusunu barindirir:
:meth:`ReservationRepository.bookings_for_range`. Cikardigi liste dogrudan
:mod:`app.domain.rules.availability` kurallarina beslenir; eksik bir suzgec
"ayni oda ayni gece iki kez satildi" hatasina, fazla bir suzgec ise bos
odanin satilamamasina yol acar.

Dort suzgec zorunludur ve hepsi bilerek SQL tarafinda uygulanir:

1. ``Reservation.status`` :data:`BLOCKING_RESERVATION_STATUSES` icinde
   olmali (taslak, iptal, gelmedi ve bekleme listesi oda bloke etmez).
2. ``Reservation.is_deleted`` yanlis olmali (mantiksal olarak silinmis
   rezervasyon envanteri tutamaz).
3. ``ReservationRoom.is_cancelled`` yanlis olmali - grup rezervasyonunda
   yalnizca **tek bir oda satiri** iptal edilmis olabilir; baslik hala
   ``confirmed`` gorunur.
4. ``ReservationRoom.room_id`` dolu olmali - oda tipi bazli, henuz oda
   atanmamis satirlar fiziksel envanteri bloke etmez.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import ColumnElement, Select, and_, or_, select

from app.domain.enums import BLOCKING_RESERVATION_STATUSES, ReservationStatus
from app.domain.rules.availability import Booking
from app.domain.value_objects import DateRange
from app.infrastructure.db.base import utcnow
from app.infrastructure.db.models.guests import Guest
from app.infrastructure.db.models.reservations import Reservation, ReservationRoom
from app.infrastructure.db.repositories.base import BaseRepository, next_sequence_number

#: Onay numarasi oneki.
CONFIRMATION_PREFIX = "RZV"

#: :meth:`ReservationRepository._blocking_rooms_select` sorgusunun satir bicimi.
#: Tam ORM nesnesi yerine sutun demeti secildigi icin tur elle yazilir; bu
#: sayede sorgu ile :meth:`ReservationRepository._to_bookings` cozumlemesi
#: birbirinden ayrisirsa tip denetiminde yakalanir.
#:
#: ``room_id`` burada ``int | None``'dir: sorgudaki ``room_id IS NOT NULL``
#: suzgeci bir **calisma zamani** garantisidir, tip sisteminde gorunmez.
#: Bu yuzden :meth:`ReservationRepository._to_bookings` daraltmayi acikca
#: yapar - suzgec ileride yanlislikla kaldirilirsa ``Booking.room_id``
#: sessizce ``None`` olmaz.
_BookingRow = tuple[int, int | None, date, date, int, str]


class ReservationRepository(BaseRepository[Reservation]):
    """Rezervasyon basliklari ve oda satirlari."""

    model = Reservation
    entity_label = "Rezervasyon"

    # ------------------------------------------------------------------
    #  Musaitlik icin veri cikarma
    # ------------------------------------------------------------------
    def bookings_for_range(
        self,
        property_id: int,
        date_range: DateRange,
        room_ids: list[int] | None = None,
    ) -> list[Booking]:
        """Araligi kesen, envanteri bloke eden oda dolulugunu dondurur.

        Yari acik aralik suzgeci
        ------------------------
        Tarih kosulu bilerek SQL'de uygulanir::

            check_in_date < aralik.end  AND  check_out_date > aralik.start

        Buradaki **kesin esitsizlikler** otelciligin ``[giris, cikis)``
        kuralinin ta kendisidir: 10-12 Agustos rezervasyonu ile 12-14
        Agustos rezervasyonu cakismaz, cunku 12 Agustos sabahi oda bosalir.
        Kosul ``<=`` yazilsaydi bitisik rezervasyonlar sahte cakisma uretir
        ve resepsiyon bos odayi satamazdi.

        Suzgeci Python'da uygulamak da kolay olurdu; SQL'de olmasinin nedeni
        yuksek sezonda tabloda on binlerce satir bulunmasi ve
        ``ix_resroom_room_dates`` indeksinin ancak boyle kullanilabilmesidir.

        Parameters
        ----------
        property_id:
            Tesis kimligi.
        date_range:
            Sorgulanan tarih araligi.
        room_ids:
            Verilirse yalnizca bu fiziksel odalar dikkate alinir; oda atama
            ekraninda aday listesi daraltmak icin kullanilir.
        """
        stmt = self._blocking_rooms_select().where(
            Reservation.property_id == property_id,
            ReservationRoom.check_in_date < date_range.end,
            ReservationRoom.check_out_date > date_range.start,
        )
        if room_ids is not None:
            if not room_ids:
                return []
            stmt = stmt.where(ReservationRoom.room_id.in_(room_ids))
        return self._to_bookings(stmt)

    def bookings_for_room(self, room_id: int, date_range: DateRange) -> list[Booking]:
        """Tek bir fiziksel odanin verilen araliktaki dolulugunu dondurur.

        Tesis kimligi istenmez: oda zaten tek bir tesise aittir. Cakisma
        kontrolu ve oda takvimi cizimi bu yolu kullanir.
        """
        stmt = self._blocking_rooms_select().where(
            ReservationRoom.room_id == room_id,
            ReservationRoom.check_in_date < date_range.end,
            ReservationRoom.check_out_date > date_range.start,
        )
        return self._to_bookings(stmt)

    def _blocking_rooms_select(self) -> Select[_BookingRow]:
        """Envanteri bloke eden oda satirlari icin ortak ``SELECT``.

        Yalnizca :class:`Booking` uretmek icin gereken sutunlar secilir; tam
        ORM nesnesi yuklemek gereksiz bellek ve ek sorgu (onay numarasi icin
        N+1) demektir.
        """
        return (
            select(
                ReservationRoom.id,
                ReservationRoom.room_id,
                ReservationRoom.check_in_date,
                ReservationRoom.check_out_date,
                Reservation.id,
                Reservation.confirmation_number,
            )
            .join(Reservation, ReservationRoom.reservation_id == Reservation.id)
            .where(
                Reservation.is_deleted.is_(False),
                Reservation.status.in_(list(BLOCKING_RESERVATION_STATUSES)),
                ReservationRoom.is_cancelled.is_(False),
                ReservationRoom.room_id.is_not(None),
            )
            .order_by(ReservationRoom.check_in_date, ReservationRoom.id)
        )

    def _to_bookings(self, stmt: Select[_BookingRow]) -> list[Booking]:
        """Sorgu satirlarini domain :class:`Booking` nesnelerine cevirir."""
        bookings: list[Booking] = []
        for row in self.session.execute(stmt).all():
            reservation_room_id, room_id, check_in, check_out, reservation_id, number = row
            if room_id is None:  # pragma: no cover - sorgu suzgeci zaten engelliyor
                continue
            bookings.append(
                Booking(
                    room_id=room_id,
                    date_range=DateRange(check_in, check_out),
                    reservation_room_id=reservation_room_id,
                    reservation_id=reservation_id,
                    confirmation_number=number,
                )
            )
        return bookings

    # ------------------------------------------------------------------
    #  Arama ve listeleme
    # ------------------------------------------------------------------
    def get_by_confirmation_number(self, number: str) -> Reservation | None:
        """Onay numarasindan rezervasyonu bulur.

        Numara veritabani genelinde benzersizdir, bu yuzden tesis kimligi
        gerekmez. Mantiksal olarak silinmis kayitlar dondurulmez.
        """
        stmt = select(Reservation).where(
            Reservation.confirmation_number == number.strip(),
            Reservation.is_deleted.is_(False),
        )
        return self.session.scalars(stmt).one_or_none()

    def search(
        self,
        property_id: int,
        *,
        query: str | None = None,
        status: ReservationStatus | None = None,
        date_range: DateRange | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Reservation]:
        """Rezervasyon listesi ekraninin sayfali arama sorgusu.

        ``query`` onay numarasi, grup adi ve **asil misafirin** ad/soyad/
        e-posta alanlarinda aranir.

        .. note::
           SQLite'in ``LIKE`` islemi yalnizca ASCII harflerde buyuk/kucuk
           harf duyarsizdir; "SEKER" aramasi "seker" kaydini bulur ama
           Turkce'ye ozgu harflerde ("I"/"i") kullanici beklentisi
           sasabilir. Tam dogru sonuc icin ilerideki PostgreSQL gecisinde
           ``citext``/``unaccent`` kullanilmalidir.

        Siralama en yeni girise gore azalandir; resepsiyon genellikle
        yaklasan/son eklenen kayitlari arar.
        """
        stmt = select(Reservation).where(
            Reservation.property_id == property_id,
            Reservation.is_deleted.is_(False),
        )
        if query:
            pattern = f"%{query.strip()}%"
            stmt = stmt.join(Guest, Reservation.primary_guest_id == Guest.id).where(
                or_(
                    Reservation.confirmation_number.ilike(pattern),
                    Reservation.group_name.ilike(pattern),
                    Guest.first_name.ilike(pattern),
                    Guest.last_name.ilike(pattern),
                    Guest.email.ilike(pattern),
                )
            )
        if status is not None:
            stmt = stmt.where(Reservation.status == status)
        if date_range is not None:
            stmt = stmt.where(
                Reservation.check_in_date < date_range.end,
                Reservation.check_out_date > date_range.start,
            )
        stmt = stmt.order_by(Reservation.check_in_date.desc(), Reservation.id.desc())
        stmt = self._paginate(stmt, limit=limit, offset=offset)
        return list(self.session.scalars(stmt).all())

    # ------------------------------------------------------------------
    #  Gunluk operasyon listeleri
    # ------------------------------------------------------------------
    def arrivals_on(self, property_id: int, day: date) -> list[ReservationRoom]:
        """O gun giris yapacak oda satirlari.

        Oda atanmamis satirlar da dondurulur: resepsiyonun giris gunu
        yapmasi gereken is zaten oda atamaktir, listeden dusurmek yanlis
        olurdu. Ayni gerekce ile bu uc gunluk liste
        :meth:`bookings_for_range`'ten farkli olarak ``room_id`` suzgeci
        uygulamaz.
        """
        return self._operational_rows(property_id, ReservationRoom.check_in_date == day)

    def departures_on(self, property_id: int, day: date) -> list[ReservationRoom]:
        """O gun cikis yapacak oda satirlari."""
        return self._operational_rows(property_id, ReservationRoom.check_out_date == day)

    def in_house_on(self, property_id: int, day: date) -> list[ReservationRoom]:
        """O gun otelde konaklayan oda satirlari.

        Yari acik aralik geregi ``giris <= gun < cikis``: cikis gunu misafir
        artik otelde sayilmaz. Gelecek bir tarih verildiginde sonuc
        "o gun otelde olmasi **beklenen**" satirlardir.
        """
        return self._operational_rows(
            property_id,
            and_(ReservationRoom.check_in_date <= day, ReservationRoom.check_out_date > day),
        )

    def _operational_rows(
        self, property_id: int, condition: ColumnElement[bool]
    ) -> list[ReservationRoom]:
        """Gunluk listeler icin ortak suzgec kumesi."""
        stmt = (
            select(ReservationRoom)
            .join(Reservation, ReservationRoom.reservation_id == Reservation.id)
            .where(
                Reservation.property_id == property_id,
                Reservation.is_deleted.is_(False),
                Reservation.status.in_(list(BLOCKING_RESERVATION_STATUSES)),
                ReservationRoom.is_cancelled.is_(False),
                condition,
            )
            .order_by(ReservationRoom.room_id, ReservationRoom.id)
        )
        return list(self.session.scalars(stmt).all())

    # ------------------------------------------------------------------
    #  Numaralandirma
    # ------------------------------------------------------------------
    def next_confirmation_number(self, property_id: int) -> str:
        """Sonraki onay numarasini uretir, or. ``RZV-2026-000123``.

        Sayac yil bazinda ve **veritabani genelinde** tutulur; cunku
        ``confirmation_number`` sutunu global ``UNIQUE`` kisitina sahiptir.
        ``property_id`` imzada bilerek birakilmistir: cok tesisli kurulumda
        onege tesis kodu eklenecektir ve o degisiklik cagiran servisleri
        etkilememelidir.

        .. warning::
           **Es zamanlilik.** Iki oturum bu yontemi ayni anda cagirirsa ayni
           numarayi alir; ikinci ``commit`` ``UNIQUE`` ihlali yer. Bu bilincli
           bir denge: ayri bir sayac tablosu her rezervasyon icin satir kilidi
           gerektirirdi ve masaustu kurulumda cakisma pratikte gorulmez.
           **Cagiran taraf** butunluk hatasini yakalayip numarayi yeniden
           uretmeli ve islemi bir kez daha denemelidir; rezervasyon kaydini
           tek bir ``session_scope`` icinde olusturmak bunu kolaylastirir.
        """
        return next_sequence_number(
            self.session,
            Reservation.confirmation_number,
            prefix=f"{CONFIRMATION_PREFIX}-{utcnow().year}-",
        )


__all__ = ["CONFIRMATION_PREFIX", "ReservationRepository"]
