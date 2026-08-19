"""ORM modelleri.

Bu modul **tum** model siniflarini iceri aktarir. Alembic'in
``--autogenerate`` ozelligi yalnizca ``Base.metadata``'ya kayitli tablolari
gorebildigi icin, yeni bir model dosyasi eklendiginde buraya da eklenmesi
gerekir; aksi halde goc uretimi o tabloyu atlar.
"""

from __future__ import annotations

from app.infrastructure.db.base import Base
from app.infrastructure.db.models.ai import (
    AIConversation,
    AIMessage,
    AIModel,
    AIProvider,
    AIUsage,
    DocumentChunk,
)
from app.infrastructure.db.models.billing import (
    CashRegisterEntry,
    Charge,
    Folio,
    Invoice,
    InvoiceLine,
    Payment,
    TaxRate,
)
from app.infrastructure.db.models.guests import (
    Agency,
    Company,
    ConsentRecord,
    Guest,
    GuestNote,
    GuestPreference,
)
from app.infrastructure.db.models.inventory import (
    InventoryItem,
    PurchaseRequest,
    PurchaseRequestLine,
    StockMovement,
    Supplier,
    Warehouse,
)
from app.infrastructure.db.models.operations import (
    HousekeepingTask,
    LostAndFoundItem,
    MaintenancePart,
    MaintenanceTicket,
    MinibarConsumption,
)
from app.infrastructure.db.models.organization import (
    Building,
    Department,
    Employee,
    Floor,
    Property,
    Shift,
)
from app.infrastructure.db.models.reservations import (
    Reservation,
    ReservationGuest,
    ReservationRoom,
    Stay,
    WaitlistEntry,
)
from app.infrastructure.db.models.rooms import (
    RatePlan,
    RatePlanRate,
    Room,
    RoomFeature,
    RoomPhoto,
    RoomType,
)
from app.infrastructure.db.models.security import (
    AuditLog,
    Permission,
    Role,
    User,
    UserSession,
)
from app.infrastructure.db.models.system import (
    Document,
    Notification,
    Service,
    Setting,
)

#: Alembic ve test yardimcilari icin tum modellerin listesi.
ALL_MODELS = (
    # organization
    Property,
    Building,
    Floor,
    Department,
    Employee,
    Shift,
    # rooms
    RoomType,
    Room,
    RoomFeature,
    RoomPhoto,
    RatePlan,
    RatePlanRate,
    # guests
    Guest,
    Company,
    Agency,
    GuestPreference,
    GuestNote,
    ConsentRecord,
    # reservations
    Reservation,
    ReservationRoom,
    ReservationGuest,
    Stay,
    WaitlistEntry,
    # billing
    Folio,
    Charge,
    Payment,
    Invoice,
    InvoiceLine,
    TaxRate,
    CashRegisterEntry,
    # operations
    HousekeepingTask,
    MaintenanceTicket,
    MaintenancePart,
    LostAndFoundItem,
    MinibarConsumption,
    # inventory
    Warehouse,
    Supplier,
    InventoryItem,
    StockMovement,
    PurchaseRequest,
    PurchaseRequestLine,
    # security
    User,
    Role,
    Permission,
    UserSession,
    AuditLog,
    # ai
    AIProvider,
    AIModel,
    AIUsage,
    AIConversation,
    AIMessage,
    DocumentChunk,
    # system
    Notification,
    Setting,
    Service,
    Document,
)

__all__ = [
    "ALL_MODELS",
    "AIConversation",
    "AIMessage",
    "AIModel",
    "AIProvider",
    "AIUsage",
    "Agency",
    "AuditLog",
    "Base",
    "Building",
    "CashRegisterEntry",
    "Charge",
    "Company",
    "ConsentRecord",
    "Department",
    "Document",
    "DocumentChunk",
    "Employee",
    "Floor",
    "Folio",
    "Guest",
    "GuestNote",
    "GuestPreference",
    "HousekeepingTask",
    "InventoryItem",
    "Invoice",
    "InvoiceLine",
    "LostAndFoundItem",
    "MaintenancePart",
    "MaintenanceTicket",
    "MinibarConsumption",
    "Notification",
    "Payment",
    "Permission",
    "Property",
    "PurchaseRequest",
    "PurchaseRequestLine",
    "RatePlan",
    "RatePlanRate",
    "Reservation",
    "ReservationGuest",
    "ReservationRoom",
    "Role",
    "Room",
    "RoomFeature",
    "RoomPhoto",
    "RoomType",
    "Service",
    "Setting",
    "Shift",
    "Stay",
    "StockMovement",
    "Supplier",
    "TaxRate",
    "User",
    "UserSession",
    "WaitlistEntry",
    "Warehouse",
]
