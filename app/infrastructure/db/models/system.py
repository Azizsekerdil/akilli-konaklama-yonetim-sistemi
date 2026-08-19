"""Sistem modelleri: bildirim, ayar, ek hizmet, belge."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
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
    DocumentType,
    NotificationType,
    Priority,
    ServiceCategory,
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
    from app.infrastructure.db.models.ai import DocumentChunk
    from app.infrastructure.db.models.security import User


class Notification(Base, TimestampMixin):
    """Kullaniciya gosterilen bildirim."""

    __table_args__ = (Index("ix_notification_user_read", "user_id", "is_read", "created_at"),)

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"),
        default=None,
        index=True,
        doc="Bos ise tum kullanicilara yayin.",
    )
    property_id: Mapped[int | None] = mapped_column(
        ForeignKey("property.id", ondelete="CASCADE"), default=None
    )

    notification_type: Mapped[NotificationType] = mapped_column(
        enum_column(NotificationType), default=NotificationType.INFO, index=True
    )
    priority: Mapped[Priority] = mapped_column(enum_column(Priority), default=Priority.NORMAL)

    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)

    is_read: Mapped[bool] = mapped_column(default=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)

    # ---- Ilgili kayda gitme ----
    entity_type: Mapped[str | None] = mapped_column(String(60), default=None)
    entity_id: Mapped[int | None] = mapped_column(default=None)
    action_url: Mapped[str | None] = mapped_column(
        String(200), default=None, doc="Arayuz ici yonlendirme, or. 'reservations/42'."
    )

    is_ai_generated: Mapped[bool] = mapped_column(
        default=False, doc="Yapay zeka tarafindan uretildiyse arayuzde isaretlenir."
    )
    expires_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)

    user: Mapped[User | None] = relationship()


class Setting(Base, TimestampMixin):
    """Veritabaninda tutulan calisma zamani ayari.

    ``.env`` ayarlari **kurulum** duzeyindedir (veritabani adresi, log
    seviyesi). Bu tablo ise **isletme** duzeyindeki, arayuzden degistirilen
    ayarlari tutar (varsayilan KDV orani, erken giris ucreti vb.).
    """

    __table_args__ = (UniqueConstraint("property_id", "key", name="uq_setting_property_key"),)

    property_id: Mapped[int | None] = mapped_column(
        ForeignKey("property.id", ondelete="CASCADE"),
        default=None,
        index=True,
        doc="Bos ise sistem geneli ayar.",
    )
    key: Mapped[str] = mapped_column(String(120), index=True)
    value: Mapped[str | None] = mapped_column(Text, default=None)
    value_type: Mapped[str] = mapped_column(
        String(20), default="str", doc="str | int | float | bool | json"
    )
    category: Mapped[str] = mapped_column(String(60), default="genel", index=True)
    label: Mapped[str | None] = mapped_column(String(200), default=None)
    description: Mapped[str | None] = mapped_column(String(400), default=None)
    is_editable: Mapped[bool] = mapped_column(default=True)
    is_sensitive: Mapped[bool] = mapped_column(
        default=False, doc="True ise arayuzde maskelenir ve loglanmaz."
    )

    def typed_value(self) -> Any:
        """Degeri ``value_type``'a gore cevirir."""
        import json

        if self.value is None:
            return None
        match self.value_type:
            case "int":
                return int(self.value)
            case "float":
                return float(self.value)
            case "bool":
                return self.value.strip().lower() in {"1", "true", "yes", "evet", "on"}
            case "json":
                return json.loads(self.value)
            case _:
                return self.value


class Service(Base, TimestampMixin, ActiveMixin, NotesMixin):
    """Ek hizmet tanimi (SPA masaji, transfer, otopark, camasir...).

    Folyoya islenen ucretler bu tanima baglanabilir; boylece hizmet bazli
    gelir raporu uretilebilir.
    """

    __table_args__ = (UniqueConstraint("property_id", "code", name="uq_service_property_code"),)

    property_id: Mapped[int] = mapped_column(ForeignKey("property.id"), index=True)
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    category: Mapped[ServiceCategory] = mapped_column(
        enum_column(ServiceCategory), default=ServiceCategory.OTHER, index=True
    )
    description: Mapped[str | None] = mapped_column(Text, default=None)

    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    currency: Mapped[Currency] = mapped_column(
        enum_column(Currency, length=10), default=Currency.TRY
    )
    tax_rate_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("20.00"))
    unit: Mapped[str] = mapped_column(String(20), default="adet")

    is_complimentary: Mapped[bool] = mapped_column(default=False, doc="Ucretsiz hizmet.")
    requires_reservation: Mapped[bool] = mapped_column(default=False)


class Document(Base, TimestampMixin, NotesMixin):
    """Sisteme yuklenen belge.

    Dosyanin kendisi ``uploads/`` altinda tutulur; burada yalnizca goreli yol
    ve ust veri saklanir. Belge metni cikarilirsa RAG icin
    :class:`~app.infrastructure.db.models.ai.DocumentChunk` satirlari uretilir.
    """

    __table_args__ = (Index("ix_document_entity", "entity_type", "entity_id"),)

    property_id: Mapped[int | None] = mapped_column(
        ForeignKey("property.id", ondelete="CASCADE"), default=None, index=True
    )
    document_type: Mapped[DocumentType] = mapped_column(
        enum_column(DocumentType), default=DocumentType.OTHER, index=True
    )

    title: Mapped[str] = mapped_column(String(250))
    file_path: Mapped[str] = mapped_column(String(500), doc="uploads/ altinda goreli yol.")
    file_name: Mapped[str] = mapped_column(String(250))
    mime_type: Mapped[str | None] = mapped_column(String(120), default=None)
    file_size_bytes: Mapped[int] = mapped_column(default=0)
    checksum_sha256: Mapped[str | None] = mapped_column(
        String(64), default=None, doc="Butunluk dogrulamasi icin."
    )

    # ---- Ilgili kayit ----
    entity_type: Mapped[str | None] = mapped_column(String(60), default=None)
    entity_id: Mapped[int | None] = mapped_column(default=None)

    # ---- RAG ----
    is_indexed: Mapped[bool] = mapped_column(
        default=False, index=True, doc="Vektor indeksine eklendi mi?"
    )
    indexed_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)
    extracted_text: Mapped[str | None] = mapped_column(Text, default=None)

    is_sensitive: Mapped[bool] = mapped_column(
        default=False,
        doc="Kimlik belgesi gibi ozel nitelikli veri iceriyorsa True; " "yapay zekaya gonderilmez.",
    )
    doc_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)

    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None
    )

    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


__all__ = ["Document", "Notification", "Service", "Setting"]
