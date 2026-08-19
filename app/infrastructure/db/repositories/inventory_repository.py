"""Stok veri erisimi.

Stok seviyesinin dogruluk kaynagi :class:`StockMovement` satirlaridir;
``InventoryItem.current_stock`` yalnizca hizli okuma icin tutulan bir
ozettir. :meth:`InventoryRepository.stock_on_hand` ozeti degil hareketleri
okur ve bu iki degerin birbirinden ayrilip ayrilmadigini kontrol etmeyi
mumkun kilar.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import and_, func, or_, select

from app.domain.enums import StockMovementType
from app.domain.value_objects import to_decimal
from app.infrastructure.db.models.inventory import InventoryItem, StockMovement
from app.infrastructure.db.repositories.base import BaseRepository


class InventoryRepository(BaseRepository[InventoryItem]):
    """Stok kartlari ve hareketleri."""

    model = InventoryItem
    entity_label = "Stok karti"

    # ------------------------------------------------------------------
    #  Uyarilar
    # ------------------------------------------------------------------
    def low_stock_items(self, property_id: int) -> list[InventoryItem]:
        """Asgari seviyenin altina dusmus aktif stok kartlarini dondurur.

        ``minimum_stock = 0`` olan kartlar hic listelenmez: asgari seviye
        tanimlanmamis bir urun icin "stok bitti" uyarisi uretmek, uyari
        listesini kullanilmaz hale getirirdi (deposu bos duran her kalem
        surekli uyari verirdi).

        Siralama en cok eksigi olan urunu basa alir; satin alma talebi bu
        sirayla hazirlanir.
        """
        deficit = InventoryItem.current_stock - InventoryItem.minimum_stock
        stmt = (
            select(InventoryItem)
            .where(
                InventoryItem.property_id == property_id,
                InventoryItem.is_active.is_(True),
                InventoryItem.minimum_stock > 0,
                InventoryItem.current_stock < InventoryItem.minimum_stock,
            )
            .order_by(deficit.asc(), InventoryItem.name)
        )
        return list(self.session.scalars(stmt).all())

    # ------------------------------------------------------------------
    #  Hareketler
    # ------------------------------------------------------------------
    def stock_on_hand(self, item_id: int) -> Decimal:
        """Eldeki stogu hareketlerden hesaplar.

        Isaret kurali
        -------------
        Miktarlar veritabaninda **her zaman pozitiftir**; yon
        :attr:`StockMovementType.sign` ile belirlenir. Hesaplama bu yuzden
        hareket turune gore gruplanip isaret Python tarafinda uygulanir:
        boylece yon kurali tek bir yerde (domain enum'unda) kalir ve SQL'e
        kopyalanmaz. Grup sayisi enum uyesi kadardir (sekiz), yani sorgu
        veri buyudukce yavaslamaz.

        Sayim duzeltmesi tuzagi
        -----------------------
        ``ADJUSTMENT`` hareketinin isareti sifirdir; yonu turden
        anlasilamaz. Bu yuzden **son sayim duzeltmesi** (``stock_after``
        dolu olan) bir taban kabul edilir ve yalnizca ondan sonraki
        hareketler toplanir. Sayim yapilmis bir urunde eski hareketleri de
        toplamak, duzeltmenin tum amacini bosa cikarirdi.

        ``stock_after`` bos birakilmis duzeltmeler taban olusturmaz ve
        toplama sifir katkiyla girer; bu durumda kayit fiilen goz ardi
        edilir. Duzeltmeleri her zaman ``stock_after`` ile kaydedin.
        """
        baseline = self.session.execute(
            select(
                StockMovement.id,
                StockMovement.movement_date,
                StockMovement.stock_after,
            )
            .where(
                StockMovement.inventory_item_id == item_id,
                StockMovement.movement_type == StockMovementType.ADJUSTMENT,
                StockMovement.stock_after.is_not(None),
            )
            .order_by(StockMovement.movement_date.desc(), StockMovement.id.desc())
            .limit(1)
        ).first()

        stmt = select(StockMovement.movement_type, func.sum(StockMovement.quantity)).where(
            StockMovement.inventory_item_id == item_id
        )
        total = Decimal("0.000")
        if baseline is not None:
            baseline_id, baseline_date, baseline_stock = baseline
            total = to_decimal(baseline_stock)
            # (tarih, id) ikilisiyle siralama: ayni gun icindeki hareketlerde
            # kayit sirasi belirleyicidir.
            stmt = stmt.where(
                or_(
                    StockMovement.movement_date > baseline_date,
                    and_(
                        StockMovement.movement_date == baseline_date,
                        StockMovement.id > baseline_id,
                    ),
                )
            )

        for movement_type, quantity in self.session.execute(
            stmt.group_by(StockMovement.movement_type)
        ).all():
            if quantity is None:
                continue
            total += to_decimal(quantity) * movement_type.sign
        return total

    def recent_movements(self, item_id: int, limit: int = 20) -> list[StockMovement]:
        """Urunun son hareketlerini en yeniden eskiye dogru dondurur.

        Ikincil siralama ``id``'dir: ayni gune ait birden fazla hareket
        varsa kayit sirasi korunur, aksi halde liste her acilista farkli
        siralanabilirdi.
        """
        stmt = (
            select(StockMovement)
            .where(StockMovement.inventory_item_id == item_id)
            .order_by(StockMovement.movement_date.desc(), StockMovement.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())


__all__ = ["InventoryRepository"]
