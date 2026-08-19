"""Domain sabitleri (enum'lar).

Her enum ``str`` tabanlidir; boylece veritabaninda okunabilir metin olarak
saklanir ve JSON'a dogrudan serilestirilebilir. Sayisal kodlar yerine metin
kullanmak, veritabanini elle inceleyen bir yoneticinin ne oldugunu anlamasini
saglar ve gocler sirasinda kod kaymasi riskini ortadan kaldirir.

Her enum, arayuzde gosterilecek Turkce etiketi :attr:`LabeledEnum.label`
uzerinden sunar.
"""

from __future__ import annotations

from enum import Enum


class LabeledEnum(str, Enum):
    """Turkce gorunen ad tasiyabilen enum tabani."""

    @property
    def label(self) -> str:
        """Arayuzde gosterilecek Turkce etiket."""
        return _LABELS.get(type(self).__name__, {}).get(self.value, self.value)

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """``(deger, etiket)`` ciftleri - acilir listeler icin."""
        return [(member.value, member.label) for member in cls]

    def __str__(self) -> str:
        return self.value


# ==========================================================================
#  Rezervasyon ve konaklama
# ==========================================================================
class ReservationStatus(LabeledEnum):
    """Rezervasyonun yasam dongusu.

    Gecerli gecisler :data:`RESERVATION_TRANSITIONS` icinde tanimlidir.
    """

    DRAFT = "draft"
    """Taslak - henuz onaylanmamis, oda blokelemez."""

    TENTATIVE = "tentative"
    """Opsiyonlu - gecici olarak tutulur, son odeme tarihi vardir."""

    CONFIRMED = "confirmed"
    """Onaylanmis - oda bloke edilir."""

    CHECKED_IN = "checked_in"
    """Misafir giris yapmis."""

    CHECKED_OUT = "checked_out"
    """Misafir cikis yapmis."""

    CANCELLED = "cancelled"
    """Iptal edilmis - oda serbest."""

    NO_SHOW = "no_show"
    """Misafir gelmedi - oda serbest, ceza uygulanabilir."""

    WAITLIST = "waitlist"
    """Bekleme listesinde - oda blokelemez."""


#: Rezervasyon durumlari arasindaki gecerli gecisler.
RESERVATION_TRANSITIONS: dict[ReservationStatus, frozenset[ReservationStatus]] = {
    ReservationStatus.DRAFT: frozenset(
        {ReservationStatus.TENTATIVE, ReservationStatus.CONFIRMED, ReservationStatus.CANCELLED}
    ),
    ReservationStatus.TENTATIVE: frozenset(
        {ReservationStatus.CONFIRMED, ReservationStatus.CANCELLED, ReservationStatus.NO_SHOW}
    ),
    ReservationStatus.CONFIRMED: frozenset(
        {
            ReservationStatus.CHECKED_IN,
            ReservationStatus.CANCELLED,
            ReservationStatus.NO_SHOW,
            ReservationStatus.TENTATIVE,
        }
    ),
    ReservationStatus.CHECKED_IN: frozenset({ReservationStatus.CHECKED_OUT}),
    ReservationStatus.CHECKED_OUT: frozenset(),
    ReservationStatus.CANCELLED: frozenset(),
    ReservationStatus.NO_SHOW: frozenset({ReservationStatus.CANCELLED}),
    ReservationStatus.WAITLIST: frozenset(
        {ReservationStatus.CONFIRMED, ReservationStatus.TENTATIVE, ReservationStatus.CANCELLED}
    ),
}

#: Odayi fiilen bloke eden (musaitlik hesabina giren) durumlar.
#: Bu kume, cakisma kontrolunun kalbidir - bkz. app.domain.rules.availability
BLOCKING_RESERVATION_STATUSES: frozenset[ReservationStatus] = frozenset(
    {
        ReservationStatus.TENTATIVE,
        ReservationStatus.CONFIRMED,
        ReservationStatus.CHECKED_IN,
    }
)

#: Rezervasyonun kapandigi, degistirilemeyecegi durumlar.
TERMINAL_RESERVATION_STATUSES: frozenset[ReservationStatus] = frozenset(
    {
        ReservationStatus.CHECKED_OUT,
        ReservationStatus.CANCELLED,
        ReservationStatus.NO_SHOW,
    }
)


class ReservationSource(LabeledEnum):
    """Rezervasyonun geldigi kanal - kanal bazli gelir analizi icin."""

    DIRECT = "direct"
    PHONE = "phone"
    WALK_IN = "walk_in"
    EMAIL = "email"
    WEBSITE = "website"
    BOOKING_COM = "booking_com"
    EXPEDIA = "expedia"
    AIRBNB = "airbnb"
    ETSTUR = "etstur"
    TATILSEPETI = "tatilsepeti"
    AGENCY = "agency"
    CORPORATE = "corporate"
    OTHER = "other"


class StayStatus(LabeledEnum):
    """Fiili konaklama kaydinin durumu."""

    IN_HOUSE = "in_house"
    DEPARTED = "departed"
    EARLY_DEPARTURE = "early_departure"


# ==========================================================================
#  Oda
# ==========================================================================
class RoomOccupancyStatus(LabeledEnum):
    """Odanin dolu/bos durumu (front-office gorunumu)."""

    VACANT = "vacant"
    OCCUPIED = "occupied"


class RoomHousekeepingStatus(LabeledEnum):
    """Odanin temizlik durumu (kat hizmetleri gorunumu)."""

    CLEAN = "clean"
    """Temiz - satisa hazir."""

    DIRTY = "dirty"
    """Kirli - temizlik bekliyor."""

    INSPECTED = "inspected"
    """Temizlenmis ve kontrol edilmis."""

    CLEANING_IN_PROGRESS = "cleaning_in_progress"
    """Temizlik devam ediyor."""

    OUT_OF_SERVICE = "out_of_service"
    """Kucuk sorun - satisa kapali ama envanterde."""

    OUT_OF_ORDER = "out_of_order"
    """Ciddi ariza - envanterden dusulur (doluluk paydasindan cikar)."""


#: Odanin satilamayacagi temizlik/bakim durumlari.
UNSELLABLE_ROOM_STATUSES: frozenset[RoomHousekeepingStatus] = frozenset(
    {RoomHousekeepingStatus.OUT_OF_SERVICE, RoomHousekeepingStatus.OUT_OF_ORDER}
)


class BedType(LabeledEnum):
    """Yatak tipi."""

    SINGLE = "single"
    TWIN = "twin"
    DOUBLE = "double"
    QUEEN = "queen"
    KING = "king"
    SOFA_BED = "sofa_bed"
    BUNK = "bunk"
    CRIB = "crib"


class RoomView(LabeledEnum):
    """Oda manzarasi - fiyatlandirmayi etkileyebilir."""

    NONE = "none"
    SEA = "sea"
    CITY = "city"
    GARDEN = "garden"
    POOL = "pool"
    MOUNTAIN = "mountain"
    COURTYARD = "courtyard"


# ==========================================================================
#  Fiyatlandirma
# ==========================================================================
class RatePlanType(LabeledEnum):
    """Fiyat plani turu."""

    STANDARD = "standard"
    NON_REFUNDABLE = "non_refundable"
    EARLY_BIRD = "early_bird"
    LAST_MINUTE = "last_minute"
    LONG_STAY = "long_stay"
    CORPORATE = "corporate"
    AGENCY = "agency"
    PACKAGE = "package"


class MealPlan(LabeledEnum):
    """Pansiyon tipi."""

    ROOM_ONLY = "room_only"
    BED_BREAKFAST = "bed_breakfast"
    HALF_BOARD = "half_board"
    FULL_BOARD = "full_board"
    ALL_INCLUSIVE = "all_inclusive"
    ULTRA_ALL_INCLUSIVE = "ultra_all_inclusive"


class Currency(LabeledEnum):
    """Desteklenen para birimleri."""

    TRY = "TRY"
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"

    @property
    def symbol(self) -> str:
        return {"TRY": "₺", "USD": "$", "EUR": "€", "GBP": "£"}[self.value]


# ==========================================================================
#  Folyo / finans
# ==========================================================================
class FolioStatus(LabeledEnum):
    """Misafir hesabi (folyo) durumu."""

    OPEN = "open"
    CLOSED = "closed"
    TRANSFERRED = "transferred"
    DISPUTED = "disputed"


class ChargeType(LabeledEnum):
    """Folyoya islenen ucret turu."""

    ROOM = "room"
    TAX = "tax"
    CITY_TAX = "city_tax"
    FOOD_BEVERAGE = "food_beverage"
    RESTAURANT = "restaurant"
    MINIBAR = "minibar"
    SPA = "spa"
    LAUNDRY = "laundry"
    TRANSFER = "transfer"
    PARKING = "parking"
    TELEPHONE = "telephone"
    INTERNET = "internet"
    DAMAGE = "damage"
    DEPOSIT = "deposit"
    EARLY_CHECKIN = "early_checkin"
    LATE_CHECKOUT = "late_checkout"
    CANCELLATION_FEE = "cancellation_fee"
    NO_SHOW_FEE = "no_show_fee"
    DISCOUNT = "discount"
    OTHER = "other"

    @property
    def is_credit(self) -> bool:
        """Folyo bakiyesini azaltan (alacak) kalem mi?"""
        return self in {ChargeType.DISCOUNT}


class PaymentMethod(LabeledEnum):
    """Odeme yontemi."""

    CASH = "cash"
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    BANK_TRANSFER = "bank_transfer"
    ONLINE = "online"
    VOUCHER = "voucher"
    CITY_LEDGER = "city_ledger"
    """Acente/kurumsal cari hesaba yazilir."""

    OTHER = "other"


class PaymentStatus(LabeledEnum):
    """Odeme durumu."""

    PENDING = "pending"
    PARTIAL = "partial"
    PAID = "paid"
    REFUNDED = "refunded"
    FAILED = "failed"
    VOIDED = "voided"


class InvoiceStatus(LabeledEnum):
    """Fatura durumu."""

    DRAFT = "draft"
    ISSUED = "issued"
    SENT = "sent"
    PAID = "paid"
    CANCELLED = "cancelled"


class TransactionDirection(LabeledEnum):
    """Kasa hareket yonu."""

    INCOME = "income"
    EXPENSE = "expense"


# ==========================================================================
#  Misafir / CRM
# ==========================================================================
class GuestTitle(LabeledEnum):
    """Hitap sekli."""

    MR = "mr"
    MRS = "mrs"
    MS = "ms"
    DR = "dr"
    PROF = "prof"
    NONE = "none"


class VIPLevel(LabeledEnum):
    """VIP siniflandirmasi."""

    NONE = "none"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"
    VVIP = "vvip"


class IdentityDocumentType(LabeledEnum):
    """Kimlik belgesi turu.

    .. note::
       Kimlik numaralari veritabaninda maskelenerek/hash'lenerek tutulur,
       loglara duz metin yazilmaz. Bkz. :mod:`app.core.logging`.
    """

    NATIONAL_ID = "national_id"
    PASSPORT = "passport"
    DRIVING_LICENSE = "driving_license"
    RESIDENCE_PERMIT = "residence_permit"
    OTHER = "other"


class GuestRelation(LabeledEnum):
    """Rezervasyondaki misafirin rolu."""

    PRIMARY = "primary"
    ACCOMPANYING = "accompanying"
    CHILD = "child"
    INFANT = "infant"


class ConsentType(LabeledEnum):
    """KVKK kapsaminda alinan izin turu."""

    DATA_PROCESSING = "data_processing"
    MARKETING_EMAIL = "marketing_email"
    MARKETING_SMS = "marketing_sms"
    PHOTO_USAGE = "photo_usage"
    PROFILING = "profiling"


# ==========================================================================
#  Kat hizmetleri
# ==========================================================================
class HousekeepingTaskType(LabeledEnum):
    """Kat hizmetleri gorev turu."""

    DAILY_CLEANING = "daily_cleaning"
    CHECKOUT_CLEANING = "checkout_cleaning"
    DEEP_CLEANING = "deep_cleaning"
    TURNDOWN = "turndown"
    LINEN_CHANGE = "linen_change"
    MINIBAR_REFILL = "minibar_refill"
    INSPECTION = "inspection"
    GUEST_REQUEST = "guest_request"


class HousekeepingStatus(LabeledEnum):
    """Kat hizmetleri gorev durumu."""

    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    INSPECTED = "inspected"
    CANCELLED = "cancelled"


class LostItemStatus(LabeledEnum):
    """Kayip esya durumu."""

    FOUND = "found"
    STORED = "stored"
    CLAIMED = "claimed"
    RETURNED = "returned"
    DISPOSED = "disposed"


# ==========================================================================
#  Teknik servis
# ==========================================================================
class MaintenanceCategory(LabeledEnum):
    """Ariza/bakim kategorisi."""

    ELECTRICAL = "electrical"
    PLUMBING = "plumbing"
    HVAC = "hvac"
    FURNITURE = "furniture"
    ELECTRONICS = "electronics"
    STRUCTURAL = "structural"
    ELEVATOR = "elevator"
    IT_NETWORK = "it_network"
    SAFETY = "safety"
    OTHER = "other"


class MaintenanceStatus(LabeledEnum):
    """Ariza kaydi durumu."""

    OPEN = "open"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    WAITING_PARTS = "waiting_parts"
    RESOLVED = "resolved"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class Priority(LabeledEnum):
    """Genel oncelik seviyesi (gorev, ariza, bildirim)."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"

    @property
    def weight(self) -> int:
        """Siralama icin sayisal agirlik (buyuk = daha acil)."""
        return {"low": 1, "normal": 2, "high": 3, "urgent": 4, "critical": 5}[self.value]


# ==========================================================================
#  Personel
# ==========================================================================
class EmploymentStatus(LabeledEnum):
    """Calisanin istihdam durumu."""

    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class ShiftType(LabeledEnum):
    """Vardiya turu."""

    MORNING = "morning"
    AFTERNOON = "afternoon"
    NIGHT = "night"
    FULL_DAY = "full_day"
    ON_CALL = "on_call"


class TaskStatus(LabeledEnum):
    """Genel gorev durumu."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    OVERDUE = "overdue"


# ==========================================================================
#  Stok
# ==========================================================================
class StockMovementType(LabeledEnum):
    """Stok hareket turu."""

    PURCHASE_IN = "purchase_in"
    RETURN_IN = "return_in"
    TRANSFER_IN = "transfer_in"
    CONSUMPTION_OUT = "consumption_out"
    MINIBAR_OUT = "minibar_out"
    WASTE_OUT = "waste_out"
    TRANSFER_OUT = "transfer_out"
    ADJUSTMENT = "adjustment"

    @property
    def sign(self) -> int:
        """Stok miktarina etkisi: +1 giris, -1 cikis, 0 duzeltme (isaret veriden gelir)."""
        if self.value.endswith("_in"):
            return 1
        if self.value.endswith("_out"):
            return -1
        return 0


class PurchaseRequestStatus(LabeledEnum):
    """Satin alma talebi durumu."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    ORDERED = "ordered"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


# ==========================================================================
#  Ek hizmetler
# ==========================================================================
class ServiceCategory(LabeledEnum):
    """Ek hizmet kategorisi."""

    RESTAURANT = "restaurant"
    BAR = "bar"
    MINIBAR = "minibar"
    SPA = "spa"
    TRANSFER = "transfer"
    PARKING = "parking"
    LAUNDRY = "laundry"
    TOUR = "tour"
    MEETING_ROOM = "meeting_room"
    OTHER = "other"


# ==========================================================================
#  Yapay zeka
# ==========================================================================
class AIProviderType(LabeledEnum):
    """Yapay zeka saglayici turu."""

    LMSTUDIO = "lmstudio"
    OPENAI = "openai"
    NVIDIA = "nvidia"
    ANTHROPIC = "anthropic"
    MOCK = "mock"

    @property
    def is_local(self) -> bool:
        """Yerelde calisan (ucretsiz, veri disari cikmayan) saglayici mi?"""
        return self in {AIProviderType.LMSTUDIO, AIProviderType.MOCK}


class AICapability(LabeledEnum):
    """Bir modelin destekledigi yetenek."""

    CHAT = "chat"
    VISION = "vision"
    EMBEDDING = "embedding"
    REASONING = "reasoning"
    TOOL_USE = "tool_use"
    JSON_MODE = "json_mode"
    LONG_CONTEXT = "long_context"
    CODE = "code"
    MATH = "math"


class AITaskType(LabeledEnum):
    """Yapay zekadan istenen is turu - kullanim ve maliyet raporlarinda gruplama."""

    GENERAL_CHAT = "general_chat"
    DAILY_SUMMARY = "daily_summary"
    OCCUPANCY_ANALYSIS = "occupancy_analysis"
    DEMAND_FORECAST = "demand_forecast"
    PRICING_SUGGESTION = "pricing_suggestion"
    REVIEW_CLASSIFICATION = "review_classification"
    SENTIMENT_ANALYSIS = "sentiment_analysis"
    MESSAGE_DRAFT = "message_draft"
    COMPLAINT_RESPONSE = "complaint_response"
    TASK_SUGGESTION = "task_suggestion"
    MAINTENANCE_PATTERN = "maintenance_pattern"
    STOCK_FORECAST = "stock_forecast"
    REPORT_SUMMARY = "report_summary"
    DOCUMENT_QA = "document_qa"
    NL_REPORT = "nl_report"
    DOCUMENT_VISION = "document_vision"
    CODE_ASSIST = "code_assist"
    EMBEDDING = "embedding"


class AIUsageStatus(LabeledEnum):
    """Bir yapay zeka cagrisinin sonucu."""

    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    FALLBACK_USED = "fallback_used"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class AIActionRisk(LabeledEnum):
    """Yapay zekanin onerdigi eylemin risk seviyesi.

    ``READ_ONLY`` disindaki her sey kullanici onayi gerektirir.
    """

    READ_ONLY = "read_only"
    LOW_WRITE = "low_write"
    HIGH_WRITE = "high_write"
    FORBIDDEN = "forbidden"


# ==========================================================================
#  Sistem / guvenlik
# ==========================================================================
class AuditAction(LabeledEnum):
    """Denetim gunlugune yazilan islem turu."""

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    LOGIN = "login"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    PERMISSION_DENIED = "permission_denied"
    EXPORT = "export"
    BACKUP = "backup"
    RESTORE = "restore"
    AI_REQUEST = "ai_request"
    AI_ACTION_APPROVED = "ai_action_approved"
    AI_ACTION_REJECTED = "ai_action_rejected"
    COMMAND_EXECUTED = "command_executed"
    COMMAND_BLOCKED = "command_blocked"
    SETTINGS_CHANGED = "settings_changed"


class NotificationType(LabeledEnum):
    """Bildirim turu."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    TASK = "task"
    ARRIVAL = "arrival"
    DEPARTURE = "departure"
    MAINTENANCE = "maintenance"
    LOW_STOCK = "low_stock"
    AI_SUGGESTION = "ai_suggestion"


class DocumentType(LabeledEnum):
    """Sisteme yuklenen belge turu."""

    IDENTITY = "identity"
    CONTRACT = "contract"
    INVOICE = "invoice"
    ROOM_PHOTO = "room_photo"
    MAINTENANCE_PHOTO = "maintenance_photo"
    POLICY = "policy"
    MANUAL = "manual"
    OTHER = "other"


class PropertyType(LabeledEnum):
    """Tesis turu."""

    HOTEL = "hotel"
    BOUTIQUE_HOTEL = "boutique_hotel"
    APART_HOTEL = "apart_hotel"
    PENSION = "pension"
    HOSTEL = "hostel"
    RESORT = "resort"
    VILLA = "villa"
    BUNGALOW = "bungalow"


# ==========================================================================
#  Turkce etiketler
# ==========================================================================
_LABELS: dict[str, dict[str, str]] = {
    "ReservationStatus": {
        "draft": "Taslak",
        "tentative": "Opsiyonlu",
        "confirmed": "Onaylandi",
        "checked_in": "Giris Yapildi",
        "checked_out": "Cikis Yapildi",
        "cancelled": "Iptal",
        "no_show": "Gelmedi",
        "waitlist": "Bekleme Listesi",
    },
    "ReservationSource": {
        "direct": "Dogrudan",
        "phone": "Telefon",
        "walk_in": "Kapidan Gelen",
        "email": "E-posta",
        "website": "Web Sitesi",
        "booking_com": "Booking.com",
        "expedia": "Expedia",
        "airbnb": "Airbnb",
        "etstur": "ETS Tur",
        "tatilsepeti": "Tatilsepeti",
        "agency": "Acente",
        "corporate": "Kurumsal",
        "other": "Diger",
    },
    "StayStatus": {
        "in_house": "Otelde",
        "departed": "Ayrildi",
        "early_departure": "Erken Ayrildi",
    },
    "RoomOccupancyStatus": {"vacant": "Bos", "occupied": "Dolu"},
    "RoomHousekeepingStatus": {
        "clean": "Temiz",
        "dirty": "Kirli",
        "inspected": "Kontrol Edildi",
        "cleaning_in_progress": "Temizleniyor",
        "out_of_service": "Servis Disi",
        "out_of_order": "Arizali",
    },
    "BedType": {
        "single": "Tek Kisilik",
        "twin": "Iki Ayri Yatak",
        "double": "Cift Kisilik",
        "queen": "Queen",
        "king": "King",
        "sofa_bed": "Cekyat",
        "bunk": "Ranza",
        "crib": "Bebek Karyolasi",
    },
    "RoomView": {
        "none": "Manzarasiz",
        "sea": "Deniz Manzarasi",
        "city": "Sehir Manzarasi",
        "garden": "Bahce Manzarasi",
        "pool": "Havuz Manzarasi",
        "mountain": "Dag Manzarasi",
        "courtyard": "Avlu Manzarasi",
    },
    "RatePlanType": {
        "standard": "Standart",
        "non_refundable": "Iade Edilemez",
        "early_bird": "Erken Rezervasyon",
        "last_minute": "Son Dakika",
        "long_stay": "Uzun Konaklama",
        "corporate": "Kurumsal",
        "agency": "Acente",
        "package": "Paket",
    },
    "MealPlan": {
        "room_only": "Sadece Oda",
        "bed_breakfast": "Oda Kahvalti",
        "half_board": "Yarim Pansiyon",
        "full_board": "Tam Pansiyon",
        "all_inclusive": "Her Sey Dahil",
        "ultra_all_inclusive": "Ultra Her Sey Dahil",
    },
    "Currency": {"TRY": "Turk Lirasi", "USD": "ABD Dolari", "EUR": "Euro", "GBP": "Sterlin"},
    "FolioStatus": {
        "open": "Acik",
        "closed": "Kapali",
        "transferred": "Devredildi",
        "disputed": "Itirazli",
    },
    "ChargeType": {
        "room": "Oda Ucreti",
        "tax": "Vergi",
        "city_tax": "Konaklama Vergisi",
        "food_beverage": "Yiyecek-Icecek",
        "restaurant": "Restoran",
        "minibar": "Minibar",
        "spa": "SPA",
        "laundry": "Camasirhane",
        "transfer": "Transfer",
        "parking": "Otopark",
        "telephone": "Telefon",
        "internet": "Internet",
        "damage": "Hasar",
        "deposit": "Depozito",
        "early_checkin": "Erken Giris",
        "late_checkout": "Gec Cikis",
        "cancellation_fee": "Iptal Ucreti",
        "no_show_fee": "Gelmeme Ucreti",
        "discount": "Indirim",
        "other": "Diger",
    },
    "PaymentMethod": {
        "cash": "Nakit",
        "credit_card": "Kredi Karti",
        "debit_card": "Banka Karti",
        "bank_transfer": "Havale/EFT",
        "online": "Online Odeme",
        "voucher": "Voucher",
        "city_ledger": "Cari Hesap",
        "other": "Diger",
    },
    "PaymentStatus": {
        "pending": "Bekliyor",
        "partial": "Kismi Odendi",
        "paid": "Odendi",
        "refunded": "Iade Edildi",
        "failed": "Basarisiz",
        "voided": "Iptal Edildi",
    },
    "InvoiceStatus": {
        "draft": "Taslak",
        "issued": "Duzenlendi",
        "sent": "Gonderildi",
        "paid": "Odendi",
        "cancelled": "Iptal",
    },
    "TransactionDirection": {"income": "Gelir", "expense": "Gider"},
    "GuestTitle": {
        "mr": "Bay",
        "mrs": "Bayan",
        "ms": "Sayin",
        "dr": "Dr.",
        "prof": "Prof.",
        "none": "-",
    },
    "VIPLevel": {
        "none": "Standart",
        "silver": "Gumus",
        "gold": "Altin",
        "platinum": "Platin",
        "vvip": "VVIP",
    },
    "IdentityDocumentType": {
        "national_id": "T.C. Kimlik Karti",
        "passport": "Pasaport",
        "driving_license": "Ehliyet",
        "residence_permit": "Ikamet Izni",
        "other": "Diger",
    },
    "GuestRelation": {
        "primary": "Asil Misafir",
        "accompanying": "Refakatci",
        "child": "Cocuk",
        "infant": "Bebek",
    },
    "ConsentType": {
        "data_processing": "Veri Isleme Izni",
        "marketing_email": "E-posta Pazarlama Izni",
        "marketing_sms": "SMS Pazarlama Izni",
        "photo_usage": "Fotograf Kullanim Izni",
        "profiling": "Profilleme Izni",
    },
    "HousekeepingTaskType": {
        "daily_cleaning": "Gunluk Temizlik",
        "checkout_cleaning": "Cikis Temizligi",
        "deep_cleaning": "Detayli Temizlik",
        "turndown": "Aksam Servisi",
        "linen_change": "Carsaf Degisimi",
        "minibar_refill": "Minibar Dolumu",
        "inspection": "Kontrol",
        "guest_request": "Misafir Talebi",
    },
    "HousekeepingStatus": {
        "pending": "Bekliyor",
        "assigned": "Atandi",
        "in_progress": "Devam Ediyor",
        "completed": "Tamamlandi",
        "inspected": "Kontrol Edildi",
        "cancelled": "Iptal",
    },
    "LostItemStatus": {
        "found": "Bulundu",
        "stored": "Depoda",
        "claimed": "Talep Edildi",
        "returned": "Iade Edildi",
        "disposed": "Imha Edildi",
    },
    "MaintenanceCategory": {
        "electrical": "Elektrik",
        "plumbing": "Tesisat",
        "hvac": "Isitma/Sogutma",
        "furniture": "Mobilya",
        "electronics": "Elektronik",
        "structural": "Yapisal",
        "elevator": "Asansor",
        "it_network": "BT/Ag",
        "safety": "Guvenlik",
        "other": "Diger",
    },
    "MaintenanceStatus": {
        "open": "Acik",
        "assigned": "Atandi",
        "in_progress": "Devam Ediyor",
        "waiting_parts": "Parca Bekliyor",
        "resolved": "Cozuldu",
        "closed": "Kapatildi",
        "cancelled": "Iptal",
    },
    "Priority": {
        "low": "Dusuk",
        "normal": "Normal",
        "high": "Yuksek",
        "urgent": "Acil",
        "critical": "Kritik",
    },
    "EmploymentStatus": {
        "active": "Aktif",
        "on_leave": "Izinli",
        "suspended": "Askida",
        "terminated": "Ayrildi",
    },
    "ShiftType": {
        "morning": "Sabah",
        "afternoon": "Ogleden Sonra",
        "night": "Gece",
        "full_day": "Tam Gun",
        "on_call": "Nobetci",
    },
    "TaskStatus": {
        "pending": "Bekliyor",
        "in_progress": "Devam Ediyor",
        "completed": "Tamamlandi",
        "cancelled": "Iptal",
        "overdue": "Gecikti",
    },
    "StockMovementType": {
        "purchase_in": "Satin Alma Girisi",
        "return_in": "Iade Girisi",
        "transfer_in": "Transfer Girisi",
        "consumption_out": "Tuketim Cikisi",
        "minibar_out": "Minibar Cikisi",
        "waste_out": "Fire/Zayi",
        "transfer_out": "Transfer Cikisi",
        "adjustment": "Sayim Duzeltmesi",
    },
    "PurchaseRequestStatus": {
        "draft": "Taslak",
        "submitted": "Gonderildi",
        "approved": "Onaylandi",
        "ordered": "Siparis Verildi",
        "partially_received": "Kismen Teslim Alindi",
        "received": "Teslim Alindi",
        "rejected": "Reddedildi",
        "cancelled": "Iptal",
    },
    "ServiceCategory": {
        "restaurant": "Restoran",
        "bar": "Bar",
        "minibar": "Minibar",
        "spa": "SPA",
        "transfer": "Transfer",
        "parking": "Otopark",
        "laundry": "Camasirhane",
        "tour": "Tur",
        "meeting_room": "Toplanti Salonu",
        "other": "Diger",
    },
    "AIProviderType": {
        "lmstudio": "LM Studio (Yerel)",
        "openai": "OpenAI Uyumlu",
        "nvidia": "NVIDIA",
        "anthropic": "Anthropic Claude",
        "mock": "Sahte (Test)",
    },
    "AICapability": {
        "chat": "Sohbet",
        "vision": "Gorsel Analiz",
        "embedding": "Vektor Gomme",
        "reasoning": "Akil Yurutme",
        "tool_use": "Arac Kullanimi",
        "json_mode": "JSON Modu",
        "long_context": "Uzun Baglam",
        "code": "Kod",
        "math": "Matematik",
    },
    "AITaskType": {
        "general_chat": "Genel Sohbet",
        "daily_summary": "Gunluk Ozet",
        "occupancy_analysis": "Doluluk Analizi",
        "demand_forecast": "Talep Tahmini",
        "pricing_suggestion": "Fiyat Onerisi",
        "review_classification": "Yorum Siniflandirma",
        "sentiment_analysis": "Duygu Analizi",
        "message_draft": "Mesaj Taslagi",
        "complaint_response": "Sikayet Yaniti",
        "task_suggestion": "Gorev Onerisi",
        "maintenance_pattern": "Bakim Deseni Analizi",
        "stock_forecast": "Stok Tahmini",
        "report_summary": "Rapor Ozeti",
        "document_qa": "Belge Soru-Cevap",
        "nl_report": "Dogal Dil Rapor",
        "document_vision": "Belge Gorsel Analizi",
        "code_assist": "Kod Yardimcisi",
        "embedding": "Vektor Gomme",
    },
    "AIUsageStatus": {
        "success": "Basarili",
        "failed": "Basarisiz",
        "timeout": "Zaman Asimi",
        "fallback_used": "Yedek Saglayici Kullanildi",
        "cancelled": "Iptal",
        "blocked": "Engellendi",
    },
    "AIActionRisk": {
        "read_only": "Salt Okunur",
        "low_write": "Dusuk Riskli Yazma",
        "high_write": "Yuksek Riskli Yazma",
        "forbidden": "Yasak",
    },
    "AuditAction": {
        "create": "Olusturma",
        "read": "Goruntuleme",
        "update": "Guncelleme",
        "delete": "Silme",
        "login": "Giris",
        "login_failed": "Basarisiz Giris",
        "logout": "Cikis",
        "permission_denied": "Yetki Reddi",
        "export": "Disa Aktarma",
        "backup": "Yedekleme",
        "restore": "Geri Yukleme",
        "ai_request": "Yapay Zeka Istegi",
        "ai_action_approved": "AI Eylemi Onaylandi",
        "ai_action_rejected": "AI Eylemi Reddedildi",
        "command_executed": "Komut Calistirildi",
        "command_blocked": "Komut Engellendi",
        "settings_changed": "Ayar Degisikligi",
    },
    "NotificationType": {
        "info": "Bilgi",
        "success": "Basarili",
        "warning": "Uyari",
        "error": "Hata",
        "task": "Gorev",
        "arrival": "Giris",
        "departure": "Cikis",
        "maintenance": "Bakim",
        "low_stock": "Dusuk Stok",
        "ai_suggestion": "Yapay Zeka Onerisi",
    },
    "DocumentType": {
        "identity": "Kimlik Belgesi",
        "contract": "Sozlesme",
        "invoice": "Fatura",
        "room_photo": "Oda Fotografi",
        "maintenance_photo": "Bakim Fotografi",
        "policy": "Politika/Prosedur",
        "manual": "Kullanim Kilavuzu",
        "other": "Diger",
    },
    "PropertyType": {
        "hotel": "Otel",
        "boutique_hotel": "Butik Otel",
        "apart_hotel": "Apart Otel",
        "pension": "Pansiyon",
        "hostel": "Hostel",
        "resort": "Tatil Koyu",
        "villa": "Villa",
        "bungalow": "Bungalov",
    },
}


__all__ = [
    "BLOCKING_RESERVATION_STATUSES",
    "RESERVATION_TRANSITIONS",
    "TERMINAL_RESERVATION_STATUSES",
    "UNSELLABLE_ROOM_STATUSES",
    "AIActionRisk",
    "AICapability",
    "AIProviderType",
    "AITaskType",
    "AIUsageStatus",
    "AuditAction",
    "BedType",
    "ChargeType",
    "ConsentType",
    "Currency",
    "DocumentType",
    "EmploymentStatus",
    "FolioStatus",
    "GuestRelation",
    "GuestTitle",
    "HousekeepingStatus",
    "HousekeepingTaskType",
    "IdentityDocumentType",
    "InvoiceStatus",
    "LabeledEnum",
    "LostItemStatus",
    "MaintenanceCategory",
    "MaintenanceStatus",
    "MealPlan",
    "NotificationType",
    "PaymentMethod",
    "PaymentStatus",
    "Priority",
    "PropertyType",
    "PurchaseRequestStatus",
    "RatePlanType",
    "ReservationSource",
    "ReservationStatus",
    "RoomHousekeepingStatus",
    "RoomOccupancyStatus",
    "RoomView",
    "ServiceCategory",
    "ShiftType",
    "StayStatus",
    "StockMovementType",
    "TaskStatus",
    "TransactionDirection",
    "VIPLevel",
]
