"""SQLAlchemy taban sinifi, isimlendirme kurallari ve ortak mixin'ler.

Isimlendirme kurallari neden onemli?
------------------------------------
SQLite, isimsiz kisitlari (constraint) ``ALTER TABLE`` ile degistiremez.
Alembic bir sutunu degistirmek istediginde tabloyu yeniden olusturur ve bunun
icin kisitlarin **adi olmalidir**. Asagidaki :data:`NAMING_CONVENTION`, her
kisita ongorulebilir bir ad verir; boylece gocler SQLite uzerinde de
sorunsuz calisir (``render_as_batch=True`` ile birlikte).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Integer, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.domain.enums import LabeledEnum
from app.infrastructure.db.types import TZDateTime

#: Tum kisitlar icin ongorulebilir isimlendirme sablonu.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)

E = TypeVar("E", bound=LabeledEnum)


def enum_column(enum_cls: type[E], **kwargs: Any) -> SAEnum:
    """Bir :class:`LabeledEnum` icin ``VARCHAR`` tabanli sutun tipi uretir.

    ``native_enum=False`` secilmesinin nedeni tasinabilirlik: PostgreSQL'in
    yerel ``ENUM`` tipi, yeni bir deger eklendiginde ``ALTER TYPE`` gerektirir
    ve SQLite'ta zaten karsiligi yoktur. ``VARCHAR`` + ``CHECK`` kisiti hem
    tasinabilir hem de goc dostudur.

    ``values_callable`` sayesinde veritabanina enum'un **degeri**
    (``"confirmed"``) yazilir, ismi (``"CONFIRMED"``) degil.
    """
    kwargs.setdefault("native_enum", False)
    kwargs.setdefault("length", 40)
    kwargs.setdefault("validate_strings", True)
    return SAEnum(
        enum_cls,
        values_callable=lambda enum: [member.value for member in enum],
        **kwargs,
    )


#: ``AIProvider`` gibi kisaltma iceren adlari dogru bolmek icin iki asamali desen.
_ACRONYM_BOUNDARY = re.compile(r"(.)([A-Z][a-z]+)")
_WORD_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")


def _to_snake_case(name: str) -> str:
    """``CamelCase`` adi ``snake_case``'e cevirir.

    >>> _to_snake_case("ReservationGuest")
    'reservation_guest'
    >>> _to_snake_case("AIProvider")
    'ai_provider'
    >>> _to_snake_case("AIUsage")
    'ai_usage'
    >>> _to_snake_case("Room")
    'room'
    """
    intermediate = _ACRONYM_BOUNDARY.sub(r"\1_\2", name)
    return _WORD_BOUNDARY.sub(r"\1_\2", intermediate).lower()


def utcnow() -> datetime:
    """Zaman dilimi bilincli (timezone-aware) simdiki UTC zamani.

    Naive ``datetime.now()`` kullanmak, yaz saati gecislerinde ve farkli
    sunucularda tutarsizlik uretir. Tum kayit zaman damgalari UTC'dir;
    arayuz gosterirken yerel saate cevirir.
    """
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Tum ORM modellerinin taban sinifi."""

    metadata = metadata

    #: Tum modeller tamsayi birincil anahtar kullanir.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    @declared_attr.directive
    def __tablename__(cls) -> str:  # noqa: N805
        """Sinif adindan ``snake_case`` tablo adi turetir.

        Ardisik buyuk harfler (kisaltmalar) dogru ayrilir::

            ReservationGuest -> reservation_guest
            AIProvider       -> ai_provider
            AIUsage          -> ai_usage

        Basit "her buyuk harften once alt cizgi" yaklasimi ``AIProvider``
        icin ``a_i_provider``, "onceki harf buyukse atla" yaklasimi ise
        ``aiprovider`` uretirdi; ikisi de yanlistir.
        """
        return _to_snake_case(cls.__name__)

    def __repr__(self) -> str:
        identifier = getattr(self, "id", None)
        label = (
            getattr(self, "name", None)
            or getattr(self, "code", None)
            or getattr(self, "number", None)
        )
        extra = f", {label!r}" if label else ""
        return f"<{type(self).__name__}(id={identifier}{extra})>"

    def to_dict(self, *, exclude: set[str] | None = None) -> dict[str, Any]:
        """Modeli sozluge cevirir (yalnizca sutunlar, iliskiler haric).

        Hassas alanlar cagiran taraf tarafindan ``exclude`` ile dislanmalidir.
        """
        skip = exclude or set()
        return {
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
            if column.name not in skip
        }


class TimestampMixin:
    """``created_at`` / ``updated_at`` sutunlari ekler."""

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime,
        default=utcnow,
        server_default=func.now(),
        nullable=False,
        index=True,
        doc="Kaydin olusturulma zamani (UTC).",
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
        nullable=False,
        doc="Kaydin son guncellenme zamani (UTC).",
    )


class SoftDeleteMixin:
    """Mantiksal silme destegi.

    Otel isletmesinde kayitlar (rezervasyon, misafir, fatura) genellikle
    **fiziksel olarak silinmez**: mali denetim ve gecmis raporlar icin
    saklanmasi gerekir. Bunun yerine ``is_deleted`` isaretlenir.
    """

    is_deleted: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
        doc="Mantiksal silme isareti. True ise kayit listelerde gosterilmez.",
    )
    deleted_at: Mapped[datetime | None] = mapped_column(TZDateTime, default=None, nullable=True)
    deleted_by_user_id: Mapped[int | None] = mapped_column(default=None, nullable=True)

    def mark_deleted(self, user_id: int | None = None) -> None:
        """Kaydi mantiksal olarak siler."""
        self.is_deleted = True
        self.deleted_at = utcnow()
        self.deleted_by_user_id = user_id

    def restore(self) -> None:
        """Mantiksal silmeyi geri alir."""
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by_user_id = None


class NotesMixin:
    """Serbest metin not alani."""

    notes: Mapped[str | None] = mapped_column(String(2000), default=None, nullable=True)


class ActiveMixin:
    """Aktif/pasif isareti - kayit silinmeden kullanimdan kaldirilir."""

    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)


__all__ = [
    "NAMING_CONVENTION",
    "ActiveMixin",
    "Base",
    "NotesMixin",
    "SoftDeleteMixin",
    "TimestampMixin",
    "enum_column",
    "metadata",
    "utcnow",
]
