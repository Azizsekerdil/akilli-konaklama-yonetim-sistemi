"""Yapay zeka saglayicilari, model katalogu, kullanim/maliyet kaydi ve RAG parcalari.

Gizlilik notu
-------------
:class:`AIProvider` tablosu **API anahtari icermez**. Yalnizca anahtarin
keyring'de hangi ad altinda arandigini (``secret_name``) tutar. Gercek deger
Windows Credential Manager'dadir; bkz. :mod:`app.core.secret_store`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    ForeignKey,
    Index,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import (
    AIProviderType,
    AITaskType,
    AIUsageStatus,
    Currency,
)
from app.infrastructure.db.base import (
    ActiveMixin,
    Base,
    NotesMixin,
    TimestampMixin,
    enum_column,
    utcnow,
)
from app.infrastructure.db.types import TZDateTime

if TYPE_CHECKING:
    from app.infrastructure.db.models.security import User
    from app.infrastructure.db.models.system import Document


class AIProvider(Base, TimestampMixin, ActiveMixin, NotesMixin):
    """Yapilandirilmis bir yapay zeka saglayicisi."""

    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    provider_type: Mapped[AIProviderType] = mapped_column(enum_column(AIProviderType), index=True)
    base_url: Mapped[str] = mapped_column(String(400))

    secret_name: Mapped[str | None] = mapped_column(
        String(80),
        default=None,
        doc="keyring'de API anahtarinin arandigi ad. ANAHTARIN KENDISI BURADA DEGILDIR.",
    )
    requires_api_key: Mapped[bool] = mapped_column(default=True)

    priority: Mapped[int] = mapped_column(
        default=0, doc="Yedek zincirinde sira; buyuk deger once denenir."
    )
    timeout_seconds: Mapped[int] = mapped_column(default=120)
    max_retries: Mapped[int] = mapped_column(default=2)

    # ---- Saglik durumu ----
    last_health_check_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)
    last_health_ok: Mapped[bool | None] = mapped_column(default=None)
    last_health_message: Mapped[str | None] = mapped_column(String(400), default=None)
    last_latency_ms: Mapped[int | None] = mapped_column(default=None)

    models: Mapped[list[AIModel]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )
    usages: Mapped[list[AIUsage]] = relationship(back_populates="provider")

    @property
    def is_local(self) -> bool:
        return self.provider_type.is_local

    @property
    def health_label(self) -> str:
        if self.last_health_ok is None:
            return "Test edilmedi"
        return "Calisiyor" if self.last_health_ok else "Ulasilamiyor"


class AIModel(Base, TimestampMixin, ActiveMixin, NotesMixin):
    """Saglayici katalogundaki tek bir model."""

    __table_args__ = (
        UniqueConstraint("provider_id", "model_id", name="uq_ai_model_provider_model"),
    )

    provider_id: Mapped[int] = mapped_column(
        ForeignKey("ai_provider.id", ondelete="CASCADE"), index=True
    )
    model_id: Mapped[str] = mapped_column(
        String(200), doc="Saglayiciya gonderilen gercek model kimligi."
    )
    display_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, default=None)

    capabilities: Mapped[list[str]] = mapped_column(
        JSON, default=list, doc="AICapability degerlerinin listesi."
    )
    context_window: Mapped[int | None] = mapped_column(default=None)
    max_output_tokens: Mapped[int | None] = mapped_column(default=None)
    supports_reasoning: Mapped[bool] = mapped_column(
        default=False,
        doc="Model 'reasoning_content' ureten bir dusunme modeli mi? "
        "True ise max_tokens daha yuksek ayarlanmalidir.",
    )

    # ---- Maliyet (yerel modellerde 0) ----
    input_cost_per_1k: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0.000000"))
    output_cost_per_1k: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0.000000"))
    cost_currency: Mapped[Currency] = mapped_column(
        enum_column(Currency, length=10), default=Currency.USD
    )

    # ---- Rol atamasi ----
    is_default_chat: Mapped[bool] = mapped_column(default=False)
    is_default_vision: Mapped[bool] = mapped_column(default=False)
    is_default_math: Mapped[bool] = mapped_column(default=False)
    is_default_embedding: Mapped[bool] = mapped_column(default=False)

    is_verified: Mapped[bool] = mapped_column(
        default=False, doc="Saglayicinin /models listesinde dogrulandi mi?"
    )
    verified_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None)

    provider: Mapped[AIProvider] = relationship(back_populates="models")

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> Decimal:
        """Bir cagrinin tahmini maliyetini hesaplar."""
        return (
            Decimal(prompt_tokens) / 1000 * self.input_cost_per_1k
            + Decimal(completion_tokens) / 1000 * self.output_cost_per_1k
        ).quantize(Decimal("0.000001"))


class AIUsage(Base):
    """Her yapay zeka cagrisinin kaydi - kullanim, gecikme ve maliyet takibi.

    Append-only; ``TimestampMixin`` yerine kendi ``created_at`` alanini tutar.
    **Istem ve yanit metinleri burada saklanmaz** (yalnizca ozet/hash);
    misafir verisi iceren istemlerin kalici olarak birikmesini onlemek icin.
    """

    __table_args__ = (
        Index("ix_ai_usage_time", "created_at"),
        Index("ix_ai_usage_task", "task_type", "created_at"),
        Index("ix_ai_usage_provider", "provider_id", "created_at"),
    )

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=utcnow, index=True, nullable=False
    )

    provider_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_provider.id", ondelete="SET NULL"), default=None, index=True
    )
    model_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_model.id", ondelete="SET NULL"), default=None
    )
    model_name: Mapped[str | None] = mapped_column(
        String(200), default=None, doc="Model silinse bile hangisi kullanildi bilinsin diye."
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None, index=True
    )

    task_type: Mapped[AITaskType] = mapped_column(
        enum_column(AITaskType), default=AITaskType.GENERAL_CHAT, index=True
    )
    status: Mapped[AIUsageStatus] = mapped_column(
        enum_column(AIUsageStatus), default=AIUsageStatus.SUCCESS, index=True
    )

    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    reasoning_tokens: Mapped[int] = mapped_column(
        default=0, doc="Dusunme modellerinde ureretilen gizli akil yurutme jetonlari."
    )
    total_tokens: Mapped[int] = mapped_column(default=0)

    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0.000000"))
    cost_currency: Mapped[Currency] = mapped_column(
        enum_column(Currency, length=10), default=Currency.USD
    )
    latency_ms: Mapped[int | None] = mapped_column(default=None)

    error_code: Mapped[str | None] = mapped_column(String(60), default=None)
    error_message: Mapped[str | None] = mapped_column(String(500), default=None)
    fell_back_from: Mapped[str | None] = mapped_column(
        String(40), default=None, doc="Yedege gecildiyse birincil saglayicinin kodu."
    )

    provider: Mapped[AIProvider | None] = relationship(back_populates="usages")
    user: Mapped[User | None] = relationship()


class AIConversation(Base, TimestampMixin):
    """Yapay Zeka Merkezi'ndeki sohbet oturumu."""

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), default=None, index=True
    )
    title: Mapped[str] = mapped_column(String(200), default="Yeni sohbet")
    task_type: Mapped[AITaskType] = mapped_column(
        enum_column(AITaskType), default=AITaskType.GENERAL_CHAT
    )
    provider_code: Mapped[str | None] = mapped_column(String(40), default=None)
    model_name: Mapped[str | None] = mapped_column(String(200), default=None)
    is_archived: Mapped[bool] = mapped_column(default=False, index=True)

    messages: Mapped[list[AIMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AIMessage.id",
    )
    user: Mapped[User | None] = relationship()


class AIMessage(Base, TimestampMixin):
    """Sohbet mesaji."""

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("ai_conversation.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), doc="system | user | assistant | tool")
    content: Mapped[str] = mapped_column(Text)
    reasoning_content: Mapped[str | None] = mapped_column(
        Text, default=None, doc="Dusunme modellerinin akil yurutme metni (varsa)."
    )

    is_ai_generated: Mapped[bool] = mapped_column(
        default=False,
        doc="True ise arayuzde 'AI tarafindan olusturuldu' rozeti gosterilir.",
    )
    token_count: Mapped[int] = mapped_column(default=0)
    model_name: Mapped[str | None] = mapped_column(String(200), default=None)

    conversation: Mapped[AIConversation] = relationship(back_populates="messages")


class DocumentChunk(Base, TimestampMixin):
    """RAG icin belge parcasi ve vektor gomulmesi.

    Gomme vektoru ``float32`` dizisi olarak ikili (BLOB) saklanir; JSON
    listesine gore hem yer hem cozumleme suresi acisindan cok daha verimlidir.
    Yardimcilar: :func:`app.ai.rag.store.encode_vector` / ``decode_vector``.
    """

    __table_args__ = (Index("ix_chunk_document", "document_id", "chunk_index"),)

    document_id: Mapped[int] = mapped_column(
        ForeignKey("document.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(default=0)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(default=0)

    embedding: Mapped[bytes | None] = mapped_column(
        LargeBinary, default=None, doc="float32 vektor (little-endian)."
    )
    embedding_model: Mapped[str | None] = mapped_column(String(200), default=None)
    embedding_dim: Mapped[int | None] = mapped_column(default=None)

    chunk_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)

    document: Mapped[Document] = relationship(back_populates="chunks")


__all__ = [
    "AIConversation",
    "AIMessage",
    "AIModel",
    "AIProvider",
    "AIUsage",
    "DocumentChunk",
]
