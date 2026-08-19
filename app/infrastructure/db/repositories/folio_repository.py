"""Folyo (misafir hesabi) veri erisimi.

Folyo satirlari **silinmez**, gecersiz kilinir (``Charge.is_void``). Bu
yuzden buradaki her toplam sorgusu ``is_void`` suzgecini tasimak
zorundadir; unutuldugunda gun sonu raporu iptal edilmis ucretleri de gelir
sayar ve kasa tutmaz.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.domain.enums import ChargeType, FolioStatus
from app.domain.value_objects import to_decimal
from app.infrastructure.db.base import utcnow
from app.infrastructure.db.models.billing import Charge, Folio
from app.infrastructure.db.repositories.base import BaseRepository, next_sequence_number

#: Folyo numarasi oneki.
FOLIO_PREFIX = "FLY"

#: Kapanmamis sayilan folyo durumlari.
#: ``TRANSFERRED`` haric tutulur - devredilen folyonun bakiyesi artik
#: hedef folyoda takip edilir, iki yerde birden gorunmemelidir.
UNSETTLED_FOLIO_STATUSES: frozenset[FolioStatus] = frozenset(
    {FolioStatus.OPEN, FolioStatus.DISPUTED}
)


class FolioRepository(BaseRepository[Folio]):
    """Folyolar, ucret satirlari ve gunluk gelir dokumu."""

    model = Folio
    entity_label = "Folyo"

    # ------------------------------------------------------------------
    #  Okuma
    # ------------------------------------------------------------------
    def open_folio_for_reservation(self, reservation_id: int) -> Folio | None:
        """Rezervasyonun **acik folyosunu** dondurur; yoksa ``None``.

        Ad bir eylem degil, otelcilikteki "acik folyo" kavramidir: folyo
        olusturma isi servis katmanindadir cunku para birimi, misafir ve
        folyo numarasi gibi kararlar is kuralidir. Repository yalnizca
        mevcut olani bulur.

        Bir rezervasyonda oda bazli birden fazla folyo acilabilir; bu
        durumda en eski (ilk acilan) folyo dondurulur - ana hesap odur.
        """
        stmt = (
            select(Folio)
            .where(
                Folio.reservation_id == reservation_id,
                Folio.status == FolioStatus.OPEN,
            )
            .order_by(Folio.id)
            .limit(1)
        )
        return self.session.scalars(stmt).one_or_none()

    def get_with_lines(self, folio_id: int) -> Folio:
        """Folyoyu ucret ve odeme satirlariyla birlikte yukler.

        ``selectinload`` kullanilir: her iliski icin **tek** ek sorgu
        calisir. ``joinedload`` secilseydi ucret ve odeme satirlarinin
        kartezyen carpimi doner (5 ucret x 3 odeme = 15 satir) ve
        SQLAlchemy'nin tekillestirmesine ragmen gereksiz veri tasinirdi.

        Kayit yoksa :class:`NotFoundError` firlatir; folyo ekrani bos sayfa
        yerine anlamli bir mesaj gostermelidir.
        """
        stmt = (
            select(Folio)
            .where(Folio.id == folio_id)
            .options(selectinload(Folio.charges), selectinload(Folio.payments))
        )
        folio = self.session.scalars(stmt).one_or_none()
        if folio is None:
            raise NotFoundError(
                self.entity_label,
                folio_id,
                detail=f"Folio id={folio_id} bulunamadi.",
            )
        return folio

    def unsettled_folios(self, property_id: int) -> list[Folio]:
        """Kapanmamis ve bakiyesi olan folyolari dondurur.

        Bakiyesi sifir veya negatif (fazla odeme) olan acik folyolar listeye
        girmez: tahsilat listesinin amaci "kimden para alinacak" sorusunu
        yanitlamaktir. Siralama bakiyeye gore azalandir.
        """
        stmt = (
            select(Folio)
            .where(
                Folio.property_id == property_id,
                Folio.status.in_(list(UNSETTLED_FOLIO_STATUSES)),
                Folio.balance > Decimal("0.00"),
            )
            .order_by(Folio.balance.desc(), Folio.id)
        )
        return list(self.session.scalars(stmt).all())

    def daily_revenue(self, property_id: int, day: date) -> dict[ChargeType, Decimal]:
        """Gunun ucret turu bazinda gelir dokumunu dondurur.

        Toplam **vergi dahil** (``total_amount``) tutarlardir ve yalnizca
        gecersiz kilinmamis satirlar sayilir. Kullanilan tarih
        ``charge_date``'tir, kaydin olusturulma zamani degil: gece denetimi
        sirasinda gecmis gune islenen bir ucret o gunun cirosuna yazilmali,
        islendigi gune degil.

        Hic hareket olmayan ucret turleri sozlukte yer almaz; cagiran taraf
        rapor sablonunda eksik turleri sifir olarak gosterir.
        """
        rows = self.session.execute(
            select(Charge.charge_type, func.sum(Charge.total_amount))
            .join(Folio, Charge.folio_id == Folio.id)
            .where(
                Folio.property_id == property_id,
                Charge.charge_date == day,
                Charge.is_void.is_(False),
            )
            .group_by(Charge.charge_type)
        ).all()
        return {
            charge_type: to_decimal(total if total is not None else Decimal("0.00"))
            for charge_type, total in rows
        }

    # ------------------------------------------------------------------
    #  Numaralandirma
    # ------------------------------------------------------------------
    def next_folio_number(self, property_id: int) -> str:
        """Sonraki folyo numarasini uretir, or. ``FLY-2026-000123``.

        ``folio_number`` global ``UNIQUE`` oldugu icin sayac yil bazinda
        veritabani genelinde tutulur; ``property_id`` ileride tesis kodlu
        onek icin imzada birakilmistir. Es zamanlilik uyarisi icin bkz.
        :func:`~app.infrastructure.db.repositories.base.next_sequence_number`.
        """
        return next_sequence_number(
            self.session,
            Folio.folio_number,
            prefix=f"{FOLIO_PREFIX}-{utcnow().year}-",
        )


__all__ = ["FOLIO_PREFIX", "UNSETTLED_FOLIO_STATUSES", "FolioRepository"]
