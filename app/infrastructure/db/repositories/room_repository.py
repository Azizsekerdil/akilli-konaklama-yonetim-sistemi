"""Oda envanteri veri erisimi.

Bu modulun en kritik gorevi :meth:`RoomRepository.blocks_for_range`: iki ayri
kaynaktan (odanin kendi durumu ve acik ariza kayitlari) gelen satisa kapatma
bilgisini tek bir :class:`~app.domain.rules.availability.RoomBlock` listesine
cevirir. Musaitlik kurali bu listeyi bekler ve veritabanini hic gormez.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, or_, select

from app.domain.enums import UNSELLABLE_ROOM_STATUSES, RoomHousekeepingStatus
from app.domain.rules.availability import RoomBlock
from app.domain.value_objects import DateRange
from app.infrastructure.db.models.operations import MaintenanceTicket
from app.infrastructure.db.models.rooms import Room
from app.infrastructure.db.repositories.base import BaseRepository
from app.infrastructure.db.repositories.operations_repository import OPEN_MAINTENANCE_STATUSES


class RoomRepository(BaseRepository[Room]):
    """Fiziksel odalar ve satisa kapatma donemleri."""

    model = Room
    entity_label = "Oda"

    # ------------------------------------------------------------------
    #  Listeleme
    # ------------------------------------------------------------------
    def list_rooms(
        self,
        property_id: int,
        *,
        room_type_id: int | None = None,
        only_sellable: bool = False,
    ) -> list[Room]:
        """Tesisin odalarini oda numarasina gore sirali dondurur.

        ``only_sellable=True`` verildiginde pasif odalar ve satisa kapali
        temizlik durumundakiler (:data:`UNSELLABLE_ROOM_STATUSES`) dislanir.
        Bu suzgec **tarihten bagimsizdir**: odanin belirli tarihlerde musait
        olup olmadigi ayrica :meth:`blocks_for_range` ve rezervasyon
        cakismasiyla belirlenir.
        """
        stmt = select(Room).where(Room.property_id == property_id)
        if room_type_id is not None:
            stmt = stmt.where(Room.room_type_id == room_type_id)
        if only_sellable:
            stmt = stmt.where(
                Room.is_active.is_(True),
                Room.housekeeping_status.not_in(list(UNSELLABLE_ROOM_STATUSES)),
            )
        return list(self.session.scalars(stmt.order_by(Room.number)).all())

    def get_by_number(self, property_id: int, number: str) -> Room | None:
        """Oda numarasindan odayi bulur; yoksa ``None``.

        Oda numarasi yalnizca **tesis icinde** benzersizdir
        (``uq_room_property_number``), bu yuzden tesis kimligi zorunludur.
        """
        stmt = select(Room).where(
            Room.property_id == property_id,
            Room.number == number.strip(),
        )
        return self.session.scalars(stmt).one_or_none()

    def rooms_by_type(self, property_id: int) -> dict[int, list[Room]]:
        """Odalari oda tipi kimligine gore gruplar.

        Musaitlik hesabi oda tipi duzeyinde yapilir ("2 standart oda bos mu"),
        oda atamasi ise fiziksel oda duzeyinde. Bu sozluk ikisi arasindaki
        koprudur ve N+1 sorgusu olmadan tek okumada kurulur.
        """
        grouped: dict[int, list[Room]] = defaultdict(list)
        for room in self.list_rooms(property_id):
            grouped[room.room_type_id].append(room)
        return dict(grouped)

    def count_rooms(self, property_id: int, *, exclude_out_of_order: bool = True) -> int:
        """Tesisin oda sayisini dondurur.

        Varsayilan olarak **arizali** (``OUT_OF_ORDER``) odalar sayilmaz.
        Otelcilikte doluluk oraninin paydasi satilabilir oda sayisidir;
        arizali odalar envanterden dusulur, aksi halde bakim isletmeyi
        haksiz yere dusuk doluluklu gosterir. ``OUT_OF_SERVICE`` odalar ise
        envanterde kalir (kucuk sorun, gun icinde satilabilir hale gelebilir)
        - ayrimi :class:`RoomHousekeepingStatus` docstring'i acikliyor.
        """
        stmt = (
            select(func.count())
            .select_from(Room)
            .where(Room.property_id == property_id, Room.is_active.is_(True))
        )
        if exclude_out_of_order:
            stmt = stmt.where(
                Room.housekeeping_status != RoomHousekeepingStatus.OUT_OF_ORDER,
            )
        return int(self.session.scalar(stmt) or 0)

    # ------------------------------------------------------------------
    #  Satisa kapatma
    # ------------------------------------------------------------------
    def blocks_for_range(self, property_id: int, date_range: DateRange) -> list[RoomBlock]:
        """Verilen aralikta satisa kapali odalari domain nesnelerine cevirir.

        Iki kaynak birlestirilir:

        1. **Odanin kendi durumu** - ``housekeeping_status`` satisa kapali
           bir degerse (:data:`UNSELLABLE_ROOM_STATUSES`) ve
           ``out_of_service_from/until`` alanlari araligi kesiyorsa.
        2. **Acik ariza kayitlari** - ``blocks_room=True`` olan ve henuz
           kapanmamis :class:`MaintenanceTicket` kayitlari
           (``block_from``/``block_until``).

        Neden ikisi birden?
        -------------------
        Teknik servis bir ariza actiginda odanin durumu her zaman aninda
        guncellenmez (personel unutur, gorev sirada bekler). Ariza kaydi
        tek basina da odayi satisa kapatabilmelidir; aksi halde bakimdaki
        oda yeniden satilir ve misafir kapida kalir.

        Tarih donusumu tuzagi
        ---------------------
        Veritabanindaki ``*_until`` alanlari **dahil** (inclusive) bir son
        gundur: "3 Agustos'a kadar kapali" 3 Agustos'u da kapsar.
        :class:`DateRange` ise yari aciktir (``[start, end)``). Bu yuzden
        donusumde bitis tarihine **bir gun eklenir**. Eklenmezse blogun son
        gunu serbest gorunur ve o gece oda satilabilirdi.

        Ucu acik bloklarda (``from``/``until`` bos) aralik istenen pencereye
        kirpilir; ikisi de bossa blok suresizdir ve ``date_range=None``
        dondurulur.
        """
        blocks: list[RoomBlock] = []
        blocks.extend(self._room_status_blocks(property_id, date_range))
        blocks.extend(self._maintenance_blocks(property_id, date_range))
        return blocks

    def _room_status_blocks(self, property_id: int, window: DateRange) -> list[RoomBlock]:
        """Odanin kendi ``out_of_service_*`` alanlarindan gelen bloklar."""
        stmt = select(Room).where(
            Room.property_id == property_id,
            Room.housekeeping_status.in_(list(UNSELLABLE_ROOM_STATUSES)),
            or_(Room.out_of_service_from.is_(None), Room.out_of_service_from < window.end),
            or_(Room.out_of_service_until.is_(None), Room.out_of_service_until >= window.start),
        )
        blocks: list[RoomBlock] = []
        for room in self.session.scalars(stmt.order_by(Room.number)).all():
            reason = room.out_of_service_reason or room.housekeeping_status.label
            blocks.append(
                RoomBlock(
                    room_id=room.id,
                    date_range=_clamped_range(
                        room.out_of_service_from, room.out_of_service_until, window
                    ),
                    reason=reason,
                )
            )
        return blocks

    def _maintenance_blocks(self, property_id: int, window: DateRange) -> list[RoomBlock]:
        """Acik ariza kayitlarindan gelen bloklar."""
        stmt = select(MaintenanceTicket).where(
            MaintenanceTicket.property_id == property_id,
            MaintenanceTicket.room_id.is_not(None),
            MaintenanceTicket.blocks_room.is_(True),
            MaintenanceTicket.status.in_(list(OPEN_MAINTENANCE_STATUSES)),
            or_(
                MaintenanceTicket.block_from.is_(None),
                MaintenanceTicket.block_from < window.end,
            ),
            or_(
                MaintenanceTicket.block_until.is_(None),
                MaintenanceTicket.block_until >= window.start,
            ),
        )
        blocks: list[RoomBlock] = []
        for ticket in self.session.scalars(stmt.order_by(MaintenanceTicket.id)).all():
            # room_id sorguda NULL disi suzuldu; tip daraltmasi icin yeniden okunur.
            room_id = ticket.room_id
            if room_id is None:  # pragma: no cover - savunma amacli
                continue
            blocks.append(
                RoomBlock(
                    room_id=room_id,
                    date_range=_clamped_range(ticket.block_from, ticket.block_until, window),
                    reason=f"{ticket.ticket_number} - {ticket.title}",
                )
            )
        return blocks


def _clamped_range(
    start: date | None,
    end_inclusive: date | None,
    window: DateRange,
) -> DateRange | None:
    """Veritabani tarihlerini yari acik :class:`DateRange`'e cevirir.

    * Iki ucu da bos ise blok **suresizdir**; ``None`` dondurulur ve
      :meth:`RoomBlock.blocks` her araligi kapali sayar.
    * Tek uc bos ise eksik uc istenen pencereden tamamlanir.
    * ``end_inclusive`` dahil oldugu icin bir gun eklenerek yari acik hale
      getirilir.

    ``window`` yalnizca **eksik ucu tamamlamak** icin kullanilir; dolu uclar
    pencereye kirpilmaz. Pencereden tasan bir blok oldugu gibi dondurulur.
    Kirpmaya gerek yoktur cunku tek tuketici :meth:`RoomBlock.blocks` bir
    **kesisim** testi yapar; kirpmak sonucu degistirmez ama blogun gercek
    suresini raporlayan arayuzlerde bilgi kaybina yol acardi.

    Bozuk veri (bitis < baslangic) durumunda ``DateRange`` hata firlatmasin
    diye blok yine suresiz kabul edilir: satilamayacak bir odayi yanlislikla
    satmaktansa fazladan kapatmak daha guvenlidir.
    """
    if start is None and end_inclusive is None:
        return None
    range_start = start if start is not None else window.start
    range_end = (end_inclusive + timedelta(days=1)) if end_inclusive is not None else window.end
    if range_end <= range_start:
        return None
    return DateRange(range_start, range_end)


__all__ = ["RoomRepository"]
