"""Stok ve satin alma: depo, tedarikci, urun karti, hareket, satin alma talebi."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import (
    Currency,
    PurchaseRequestStatus,
    StockMovementType,
)
from app.infrastructure.db.base import (
    ActiveMixin,
    Base,
    NotesMixin,
    TimestampMixin,
    enum_column,
)
from app.infrastructure.db.types import TZDateTime

if TYPE_CHECKING:
    from app.infrastructure.db.models.organization import Property
    from app.infrastructure.db.models.security import User


class Warehouse(Base, TimestampMixin, ActiveMixin, NotesMixin):
    """Depo / stok noktasi (ana depo, kat deposu, bar deposu...)."""

    __table_args__ = (UniqueConstraint("property_id", "code", name="uq_warehouse_property_code"),)

    property_id: Mapped[int] = mapped_column(ForeignKey("property.id"), index=True)
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(120))
    location: Mapped[str | None] = mapped_column(String(200), default=None)
    is_default: Mapped[bool] = mapped_column(default=False)

    hotel_property: Mapped[Property] = relationship()
    movements: Mapped[list[StockMovement]] = relationship(back_populates="warehouse")


class Supplier(Base, TimestampMixin, ActiveMixin, NotesMixin):
    """Tedarikci."""

    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    contact_person: Mapped[str | None] = mapped_column(String(150), default=None)
    phone: Mapped[str | None] = mapped_column(String(40), default=None)
    email: Mapped[str | None] = mapped_column(String(200), default=None)
    address_line: Mapped[str | None] = mapped_column(String(300), default=None)
    tax_office: Mapped[str | None] = mapped_column(String(120), default=None)
    tax_number: Mapped[str | None] = mapped_column(String(30), default=None)
    payment_terms_days: Mapped[int] = mapped_column(default=30)
    rating: Mapped[int | None] = mapped_column(default=None, doc="1-5 tedarikci degerlendirmesi.")

    items: Mapped[list[InventoryItem]] = relationship(back_populates="preferred_supplier")
    purchase_requests: Mapped[list[PurchaseRequest]] = relationship(back_populates="supplier")


class InventoryItem(Base, TimestampMixin, ActiveMixin, NotesMixin):
    """Stok kartı (urun tanimi).

    ``current_stock`` denormalize bir ozettir; gercek dogruluk kaynagi
    :class:`StockMovement` satirlaridir. Hareket eklendiginde servis katmani
    bu alani gunceller (bkz. ``app.application.services.inventory_service``).
    """

    __table_args__ = (
        UniqueConstraint("property_id", "sku", name="uq_inventory_property_sku"),
        Index("ix_inventory_low_stock", "property_id", "current_stock", "minimum_stock"),
    )

    property_id: Mapped[int] = mapped_column(ForeignKey("property.id"), index=True)
    sku: Mapped[str] = mapped_column(String(40), doc="Stok kodu.")
    barcode: Mapped[str | None] = mapped_column(String(60), default=None, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    category: Mapped[str] = mapped_column(
        String(80), index=True, doc="Or. 'Minibar', 'Temizlik', 'Kirtasiye'."
    )
    unit: Mapped[str] = mapped_column(String(20), default="adet", doc="Olcu birimi.")
    description: Mapped[str | None] = mapped_column(Text, default=None)

    # ---- Stok ----
    current_stock: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0.000"))
    minimum_stock: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), default=Decimal("0.000"), doc="Bu seviyenin altinda uyari uretilir."
    )
    maximum_stock: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), default=None)
    reorder_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0.000"))

    # ---- Fiyat ----
    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), doc="Ortalama alis maliyeti."
    )
    sale_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), doc="Misafire satis fiyati (minibar vb.)."
    )
    currency: Mapped[Currency] = mapped_column(
        enum_column(Currency, length=10), default=Currency.TRY
    )
    tax_rate_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("20.00"))

    is_minibar_item: Mapped[bool] = mapped_column(default=False, index=True)
    preferred_supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("supplier.id", ondelete="SET NULL"), default=None
    )

    preferred_supplier: Mapped[Supplier | None] = relationship(back_populates="items")
    movements: Mapped[list[StockMovement]] = relationship(back_populates="item")

    @property
    def is_below_minimum(self) -> bool:
        """Stok asgari seviyenin altina dustu mu?"""
        return self.current_stock < self.minimum_stock

    @property
    def stock_value(self) -> Decimal:
        """Eldeki stogun maliyet degeri."""
        return (self.current_stock * self.unit_cost).quantize(Decimal("0.01"))


class StockMovement(Base, TimestampMixin, NotesMixin):
    """Stok giris/cikis hareketi - stok seviyesinin dogruluk kaynagi."""

    __table_args__ = (
        Index("ix_stock_move_item_date", "inventory_item_id", "movement_date"),
        Index("ix_stock_move_type", "movement_type", "movement_date"),
    )

    inventory_item_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_item.id", ondelete="CASCADE"), index=True
    )
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouse.id", ondelete="SET NULL"), default=None, index=True
    )
    movement_type: Mapped[StockMovementType] = mapped_column(
        enum_column(StockMovementType), index=True
    )

    movement_date: Mapped[date] = mapped_column(Date, index=True)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), doc="Her zaman pozitif; yon movement_type'tan gelir."
    )
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    total_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))

    stock_after: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3), default=None, doc="Hareket sonrasi stok - denetim izi icin."
    )
    reference: Mapped[str | None] = mapped_column(
        String(120), default=None, doc="Irsaliye/fatura no, oda no vb."
    )
    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("room.id", ondelete="SET NULL"), default=None
    )
    recorded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None
    )

    item: Mapped[InventoryItem] = relationship(back_populates="movements")
    warehouse: Mapped[Warehouse | None] = relationship(back_populates="movements")

    @property
    def signed_quantity(self) -> Decimal:
        """Stoga etkisi (giris pozitif, cikis negatif)."""
        return self.quantity * self.movement_type.sign


class PurchaseRequest(Base, TimestampMixin, NotesMixin):
    """Satin alma talebi."""

    __table_args__ = (Index("ix_purchase_status", "status", "request_date"),)

    property_id: Mapped[int] = mapped_column(ForeignKey("property.id"), index=True)
    request_number: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("supplier.id", ondelete="SET NULL"), default=None, index=True
    )

    status: Mapped[PurchaseRequestStatus] = mapped_column(
        enum_column(PurchaseRequestStatus), default=PurchaseRequestStatus.DRAFT, index=True
    )
    request_date: Mapped[date] = mapped_column(Date, index=True)
    expected_date: Mapped[date | None] = mapped_column(Date, default=None)
    received_date: Mapped[date | None] = mapped_column(Date, default=None)

    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    currency: Mapped[Currency] = mapped_column(
        enum_column(Currency, length=10), default=Currency.TRY
    )

    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None
    )
    approved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None
    )
    approved_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)
    rejection_reason: Mapped[str | None] = mapped_column(String(400), default=None)

    supplier: Mapped[Supplier | None] = relationship(back_populates="purchase_requests")
    lines: Mapped[list[PurchaseRequestLine]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )
    requested_by: Mapped[User | None] = relationship(foreign_keys=[requested_by_user_id])

    def recalculate(self) -> None:
        self.total_amount = sum((line.total_amount for line in self.lines), start=Decimal("0.00"))


class PurchaseRequestLine(Base, TimestampMixin):
    """Satin alma talebi kalemi."""

    request_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_request.id", ondelete="CASCADE"), index=True
    )
    inventory_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_item.id", ondelete="SET NULL"), default=None
    )
    description: Mapped[str] = mapped_column(String(250))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("1.000"))
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal("0.000"))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))

    request: Mapped[PurchaseRequest] = relationship(back_populates="lines")
    inventory_item: Mapped[InventoryItem | None] = relationship()

    @property
    def is_fully_received(self) -> bool:
        return self.received_quantity >= self.quantity


__all__ = [
    "InventoryItem",
    "PurchaseRequest",
    "PurchaseRequestLine",
    "StockMovement",
    "Supplier",
    "Warehouse",
]
