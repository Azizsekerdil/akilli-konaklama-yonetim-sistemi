"""Repository katmani - servis katmaninin veri erisim yuzu.

Katman kurali
-------------
``ui -> application -> domain <- infrastructure``

Repository'ler altyapi katmanindadir: SQLAlchemy'yi bilirler, domain
kurallarini bilmezler. Yaptiklari donusum tek yonludur - ORM satirlarindan
domain veri yapilarina (:class:`~app.domain.rules.availability.Booking`,
:class:`~app.domain.rules.availability.RoomBlock`). Boylece is kurallari
veritabani olmadan test edilebilir kalir.

Kullanim::

    with session_scope() as session:
        rooms = RoomRepository(session)
        reservations = ReservationRepository(session)

        bookings = reservations.bookings_for_range(property_id, aralik)
        blocks = rooms.blocks_for_range(property_id, aralik)
        check_availability(aralik, room_id=5, existing_bookings=bookings, blocks=blocks)

Hicbir repository ``commit`` etmez; islem sinirlari cagirana aittir.
"""

from __future__ import annotations

from app.infrastructure.db.repositories.base import BaseRepository, next_sequence_number
from app.infrastructure.db.repositories.folio_repository import FolioRepository
from app.infrastructure.db.repositories.guest_repository import GuestRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.operations_repository import OperationsRepository
from app.infrastructure.db.repositories.reservation_repository import ReservationRepository
from app.infrastructure.db.repositories.room_repository import RoomRepository

__all__ = [
    "BaseRepository",
    "FolioRepository",
    "GuestRepository",
    "InventoryRepository",
    "OperationsRepository",
    "ReservationRepository",
    "RoomRepository",
    "next_sequence_number",
]
