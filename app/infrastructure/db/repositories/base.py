"""Repository katmaninin taban sinifi ve ortak yardimcilari.

Neden repository?
-----------------
Servis katmani is kurallarini uygular; SQL yazmak onun isi degildir. Domain
kurallari (:mod:`app.domain.rules`) ise saf veri yapilari bekler ve
SQLAlchemy'yi hic tanimaz. Repository'ler tam ortada durur: ORM satirlarini
okur, gerektiginde domain veri yapilarina cevirir ve servise verir. Boylece
bir sorgu degistiginde yalnizca tek bir dosya degisir, is kurallari testleri
etkilenmez.

Islem (transaction) sinirlari
-----------------------------
Repository'ler **commit etmez**. Yalnizca gerektiginde ``flush`` cagirir ki
yeni kaydin birincil anahtari hemen okunabilsin. ``commit``/``rollback``
karari cagiran servise (genellikle :func:`app.infrastructure.db.session
.session_scope`) aittir; aksi halde tek bir is akisinin ortasinda yarim
kalmis kayitlar veritabanina yazilabilirdi.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar, cast

from sqlalchemy import Select, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.core.exceptions import NotFoundError
from app.infrastructure.db.base import Base, SoftDeleteMixin

#: Repository'nin yonettigi ORM model turu.
ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Her ORM modeli icin ortak olan temel veri erisim islemleri.

    Alt siniflar yalnizca :attr:`model` (ve tercihen :attr:`entity_label`)
    tanimlar::

        class RoomRepository(BaseRepository[Room]):
            model = Room
            entity_label = "Oda"

    Mantiksal silme
    ---------------
    Model :class:`~app.infrastructure.db.base.SoftDeleteMixin` tasiyorsa
    tum okuma islemleri varsayilan olarak ``is_deleted=False`` suzgeci
    uygular. Silinen kayitlari bilerek gormek gerektiginde (denetim, geri
    alma ekrani) ``include_deleted=True`` verilir. Suzgecin varsayilan olarak
    **acik** olmasi bilinclidir: unutuldugunda "silinmis rezervasyon hala
    oda bloke ediyor" gibi sessiz ve tehlikeli hatalar olusur.
    """

    #: Alt sinifin yonettigi ORM modeli.
    model: type[ModelT]

    #: :class:`NotFoundError` mesajinda gecen Turkce kayit adi.
    entity_label: str = "Kayit"

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    #  Yardimcilar
    # ------------------------------------------------------------------
    @classmethod
    def supports_soft_delete(cls) -> bool:
        """Model mantiksal silmeyi destekliyor mu?"""
        return issubclass(cls.model, SoftDeleteMixin)

    @classmethod
    def _soft_delete_model(cls) -> type[SoftDeleteMixin]:
        """``is_deleted``/``mark_deleted`` erisimi icin daraltilmis model turu.

        :data:`ModelT` yalnizca :class:`Base`'e baglidir; mantiksal silme
        alanlari ise sadece :class:`SoftDeleteMixin` tasiyan modellerde
        bulunur. Daraltma tek bir yerde toplanir ki her cagri noktasina
        ``cast`` serpistirilmesin. **Cagirmadan once**
        :meth:`supports_soft_delete` ile kontrol etmek zorunludur; aksi halde
        calisma zamaninda ``AttributeError`` alinir.
        """
        return cast("type[SoftDeleteMixin]", cls.model)

    @staticmethod
    def _as_soft_deletable(entity: ModelT) -> SoftDeleteMixin:
        """Tekil kayit icin ayni daraltma - bkz. :meth:`_soft_delete_model`."""
        return cast("SoftDeleteMixin", entity)

    def _base_select(self, *, include_deleted: bool = False) -> Select[tuple[ModelT]]:
        """Mantiksal silme suzgeci uygulanmis temel ``SELECT``."""
        stmt = select(self.model)
        if not include_deleted and self.supports_soft_delete():
            stmt = stmt.where(self._soft_delete_model().is_deleted.is_(False))
        return stmt

    @staticmethod
    def _paginate(
        stmt: Select[Any],
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Select[Any]:
        """``LIMIT``/``OFFSET`` uygular.

        ``offset`` verilip ``limit`` verilmezse SQLAlchemy, SQLite icin
        gerekli olan ``LIMIT -1`` ifadesini kendisi uretir; bu yuzden ikisi
        bagimsiz olarak kullanilabilir.
        """
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        return stmt

    # ------------------------------------------------------------------
    #  Okuma
    # ------------------------------------------------------------------
    def get(self, entity_id: int, *, include_deleted: bool = False) -> ModelT | None:
        """Birincil anahtara gore kaydi dondurur; yoksa ``None``.

        ``Session.get`` kullanilir: kayit oturum kimlik haritasinda (identity
        map) zaten varsa veritabanina hic gidilmez.
        """
        entity = self.session.get(self.model, entity_id)
        if entity is None:
            return None
        if (
            not include_deleted
            and self.supports_soft_delete()
            and self._as_soft_deletable(entity).is_deleted
        ):
            return None
        return entity

    def get_or_404(self, entity_id: int, *, include_deleted: bool = False) -> ModelT:
        """Kaydi dondurur, yoksa :class:`NotFoundError` firlatir.

        Cagiran tarafta ``if x is None: raise ...`` tekrarini ortadan kaldirir
        ve kullaniciya her yerde ayni Turkce mesajin gitmesini saglar.
        """
        entity = self.get(entity_id, include_deleted=include_deleted)
        if entity is None:
            raise NotFoundError(
                self.entity_label,
                entity_id,
                detail=f"{self.model.__name__} id={entity_id} bulunamadi.",
            )
        return entity

    def list(
        self,
        *,
        limit: int | None = None,
        offset: int | None = None,
        include_deleted: bool = False,
        order_by: Any | None = None,
    ) -> list[ModelT]:
        """Kayitlari sayfali olarak listeler.

        Siralama verilmezse birincil anahtara gore artan siralanir; boylece
        sayfalama tekrarli cagrilarda tutarli sonuc verir (siralamasiz
        ``LIMIT/OFFSET`` ayni kaydi iki sayfada gosterebilir).

        Ad, yerlesik ``list`` isleviyle ayni: bu bilincli bir tercihtir,
        repository sozlugunun standart adidir ve yalnizca sinif icinde
        gorunur oldugu icin modul duzeyindeki ``list``'i golgelemez.
        """
        stmt = self._base_select(include_deleted=include_deleted)
        stmt = stmt.order_by(order_by if order_by is not None else self.model.id)
        stmt = self._paginate(stmt, limit=limit, offset=offset)
        return list(self.session.scalars(stmt).all())

    def count(self, *, include_deleted: bool = False) -> int:
        """Kayit sayisini dondurur."""
        stmt = select(func.count()).select_from(self.model)
        if not include_deleted and self.supports_soft_delete():
            stmt = stmt.where(self._soft_delete_model().is_deleted.is_(False))
        return int(self.session.scalar(stmt) or 0)

    def exists(self, entity_id: int, *, include_deleted: bool = False) -> bool:
        """Kayit var mi?"""
        return self.get(entity_id, include_deleted=include_deleted) is not None

    # ------------------------------------------------------------------
    #  Yazma
    # ------------------------------------------------------------------
    def add(self, entity: ModelT, *, flush: bool = True) -> ModelT:
        """Kaydi oturuma ekler ve (varsayilan olarak) ``flush`` eder.

        ``flush`` sayesinde ``entity.id`` cagri doner donmez okunabilir; bu,
        rezervasyon + oda satirlari gibi ic ice kayit olusturan akislarda
        gereklidir. Commit yapilmaz - bkz. modul docstring'i.
        """
        self.session.add(entity)
        if flush:
            self.session.flush()
        return entity

    def delete(self, entity: ModelT, *, user_id: int | None = None, hard: bool = False) -> None:
        """Kaydi siler.

        Model mantiksal silmeyi destekliyorsa varsayilan davranis
        ``is_deleted`` isaretlemektir; mali denetim izi ve gecmis raporlar
        icin kayitlarin fiziksel olarak kaybolmamasi gerekir. ``hard=True``
        yalnizca gercekten kalici silme istendiginde (or. KVKK unutulma
        talebi) kullanilmalidir.
        """
        if not hard and self.supports_soft_delete():
            self._as_soft_deletable(entity).mark_deleted(user_id)
        else:
            self.session.delete(entity)
        self.session.flush()


def next_sequence_number(
    session: Session,
    column: InstrumentedAttribute[str],
    *,
    prefix: str,
    width: int = 6,
) -> str:
    """``<onek><sira>`` bicimli bir sonraki numarayi uretir.

    Ornek: ``prefix="RZV-2026-"`` ve mevcut en buyuk numara
    ``RZV-2026-000122`` ise sonuc ``RZV-2026-000123`` olur.

    Neden ``MAX()`` metin uzerinde calisiyor?
    -----------------------------------------
    Sira numarasi **sabit genislikte ve basi sifirli** yazildigi icin
    metinsel (sozluk) siralama ile sayisal siralama ayni sonucu verir.
    ``width`` asilirsa (999999'dan fazla kayit) bu esitlik bozulur; o
    noktada numara bicimi genisletilmelidir.

    .. warning::
       Bu yardimci **es zamanli cagrilarda benzersizlik garanti etmez**.
       Iki oturum ayni anda cagirirsa ayni numarayi alabilir ve ikincisi
       ``UNIQUE`` kisitindan ``IntegrityError`` yer. Dogru kullanim, cagiran
       tarafin ``commit`` sirasindaki butunluk hatasini yakalayip numarayi
       yeniden uretmesidir (kisa bir yeniden deneme dongusu). Bu tasarim
       bilinclidir: masaustu tek-kullanicili kurulumda cakisma pratikte
       imkansizdir, ayri bir sayac tablosu ise her numara icin kilit
       gerektirirdi.
    """
    last = session.scalar(select(func.max(column)).where(column.like(f"{prefix}%")))
    sequence = 1
    if last:
        tail = last[len(prefix) :]
        if tail.isdigit():
            sequence = int(tail) + 1
    return f"{prefix}{sequence:0{width}d}"


__all__ = ["BaseRepository", "ModelT", "next_sequence_number"]
