"""Izin katalogu ve varsayilan roller.

Izinler ``modul.eylem`` bicimindedir. Kod icinde **her zaman izin kodu**
kontrol edilir, rol adi degil::

    @require_permission(Perm.RESERVATION_CREATE)
    def create_reservation(...): ...

Boylece isletme yeni bir rol tanimladiginda (or. "Gece Muduru") kaynak kodu
degistirmek gerekmez; role ilgili izinler atanir ve is biter.

Joker destegi: ``reservation.*`` izni, ``reservation`` modulunun tum
eylemlerini kapsar (bkz. :meth:`app.infrastructure.db.models.security.User.has_permission`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final


class Perm:
    """Izin kodu sabitleri.

    Dizge yerine sabit kullanmak, yazim hatalarini calisma aninda sessiz bir
    "yetki yok" yerine aninda ``AttributeError`` haline getirir.
    """

    # ---- Panel ----
    DASHBOARD_VIEW: Final = "dashboard.view"

    # ---- Tesis / oda ----
    PROPERTY_VIEW: Final = "property.view"
    PROPERTY_MANAGE: Final = "property.manage"
    ROOM_VIEW: Final = "room.view"
    ROOM_MANAGE: Final = "room.manage"
    ROOM_STATUS_CHANGE: Final = "room.status_change"
    ROOM_BLOCK: Final = "room.block"

    # ---- Fiyat ----
    RATE_VIEW: Final = "rate.view"
    RATE_MANAGE: Final = "rate.manage"

    # ---- Rezervasyon ----
    RESERVATION_VIEW: Final = "reservation.view"
    RESERVATION_CREATE: Final = "reservation.create"
    RESERVATION_EDIT: Final = "reservation.edit"
    RESERVATION_CANCEL: Final = "reservation.cancel"
    RESERVATION_OVERRIDE: Final = "reservation.override"
    """Cakisma/kural uyarilarini asma yetkisi - yalnizca yoneticiye verilir."""

    # ---- Misafir ----
    GUEST_VIEW: Final = "guest.view"
    GUEST_CREATE: Final = "guest.create"
    GUEST_EDIT: Final = "guest.edit"
    GUEST_DELETE: Final = "guest.delete"
    GUEST_VIEW_IDENTITY: Final = "guest.view_identity"
    """Sifreli kimlik numarasini acik gorme yetkisi."""

    GUEST_BLACKLIST: Final = "guest.blacklist"
    GUEST_EXPORT: Final = "guest.export"

    # ---- On buro ----
    FRONTDESK_CHECKIN: Final = "frontdesk.checkin"
    FRONTDESK_CHECKOUT: Final = "frontdesk.checkout"
    FRONTDESK_EARLY_LATE: Final = "frontdesk.early_late"

    # ---- Folyo / finans ----
    FOLIO_VIEW: Final = "folio.view"
    FOLIO_POST_CHARGE: Final = "folio.post_charge"
    FOLIO_VOID_CHARGE: Final = "folio.void_charge"
    FOLIO_DISCOUNT: Final = "folio.discount"
    PAYMENT_VIEW: Final = "payment.view"
    PAYMENT_RECEIVE: Final = "payment.receive"
    PAYMENT_REFUND: Final = "payment.refund"
    INVOICE_VIEW: Final = "invoice.view"
    INVOICE_ISSUE: Final = "invoice.issue"
    FINANCE_VIEW: Final = "finance.view"
    FINANCE_MANAGE: Final = "finance.manage"
    FINANCE_DAY_CLOSE: Final = "finance.day_close"

    # ---- Kat hizmetleri ----
    HOUSEKEEPING_VIEW: Final = "housekeeping.view"
    HOUSEKEEPING_ASSIGN: Final = "housekeeping.assign"
    HOUSEKEEPING_COMPLETE: Final = "housekeeping.complete"
    HOUSEKEEPING_INSPECT: Final = "housekeeping.inspect"
    LOSTFOUND_MANAGE: Final = "lostfound.manage"

    # ---- Teknik servis ----
    MAINTENANCE_VIEW: Final = "maintenance.view"
    MAINTENANCE_CREATE: Final = "maintenance.create"
    MAINTENANCE_ASSIGN: Final = "maintenance.assign"
    MAINTENANCE_RESOLVE: Final = "maintenance.resolve"

    # ---- Personel ----
    EMPLOYEE_VIEW: Final = "employee.view"
    EMPLOYEE_MANAGE: Final = "employee.manage"
    SHIFT_MANAGE: Final = "shift.manage"

    # ---- Stok ----
    INVENTORY_VIEW: Final = "inventory.view"
    INVENTORY_MANAGE: Final = "inventory.manage"
    INVENTORY_MOVE: Final = "inventory.move"
    PURCHASE_VIEW: Final = "purchase.view"
    PURCHASE_CREATE: Final = "purchase.create"
    PURCHASE_APPROVE: Final = "purchase.approve"

    # ---- Rapor ----
    REPORT_VIEW: Final = "report.view"
    REPORT_FINANCIAL: Final = "report.financial"
    REPORT_EXPORT: Final = "report.export"

    # ---- Yapay zeka ----
    AI_USE: Final = "ai.use"
    AI_CONFIGURE: Final = "ai.configure"
    AI_APPROVE_ACTION: Final = "ai.approve_action"
    """Yapay zekanin onerdigi veri degistiren eylemi onaylama yetkisi."""

    AI_VIEW_USAGE: Final = "ai.view_usage"

    # ---- AI Gelistirme Merkezi ----
    DEVCENTER_USE: Final = "devcenter.use"
    DEVCENTER_EXECUTE: Final = "devcenter.execute"
    """Onaylanmis komutu fiilen calistirma yetkisi."""

    DEVCENTER_APPLY_PATCH: Final = "devcenter.apply_patch"

    # ---- Sistem ----
    USER_VIEW: Final = "user.view"
    USER_MANAGE: Final = "user.manage"
    ROLE_MANAGE: Final = "role.manage"
    SETTINGS_VIEW: Final = "settings.view"
    SETTINGS_MANAGE: Final = "settings.manage"
    AUDIT_VIEW: Final = "audit.view"
    BACKUP_RUN: Final = "backup.run"
    BACKUP_RESTORE: Final = "backup.restore"


@dataclass(frozen=True, slots=True)
class PermissionSpec:
    """Bir iznin tanimi - ilk kurulumda veritabanina yazilir."""

    code: str
    name: str
    category: str
    description: str = ""
    is_dangerous: bool = False


@dataclass(frozen=True, slots=True)
class RoleSpec:
    """Bir varsayilan rolun tanimi."""

    code: str
    name: str
    description: str
    permissions: tuple[str, ...] = field(default_factory=tuple)
    is_system: bool = True


P = PermissionSpec

#: Sistemdeki tum izinler. Ilk kurulumda ve her surum yukseltmesinde
#: veritabaniyla senkronlanir (bkz. app.security.bootstrap).
PERMISSIONS: tuple[PermissionSpec, ...] = (
    P(Perm.DASHBOARD_VIEW, "Panel goruntuleme", "Panel"),
    # Tesis / oda
    P(Perm.PROPERTY_VIEW, "Tesis bilgilerini goruntuleme", "Tesis"),
    P(Perm.PROPERTY_MANAGE, "Tesis bilgilerini duzenleme", "Tesis", is_dangerous=True),
    P(Perm.ROOM_VIEW, "Odalari goruntuleme", "Oda"),
    P(Perm.ROOM_MANAGE, "Oda ve oda tipi yonetimi", "Oda", is_dangerous=True),
    P(Perm.ROOM_STATUS_CHANGE, "Oda durumu degistirme", "Oda"),
    P(Perm.ROOM_BLOCK, "Odayi satisa kapatma", "Oda", is_dangerous=True),
    # Fiyat
    P(Perm.RATE_VIEW, "Fiyatlari goruntuleme", "Fiyat"),
    P(Perm.RATE_MANAGE, "Fiyat plani ve sezon yonetimi", "Fiyat", is_dangerous=True),
    # Rezervasyon
    P(Perm.RESERVATION_VIEW, "Rezervasyonlari goruntuleme", "Rezervasyon"),
    P(Perm.RESERVATION_CREATE, "Rezervasyon olusturma", "Rezervasyon"),
    P(Perm.RESERVATION_EDIT, "Rezervasyon duzenleme", "Rezervasyon"),
    P(Perm.RESERVATION_CANCEL, "Rezervasyon iptali", "Rezervasyon", is_dangerous=True),
    P(
        Perm.RESERVATION_OVERRIDE,
        "Kural uyarilarini asma",
        "Rezervasyon",
        "Cakisma ve konaklama kurali uyarilarini gecersiz kilar.",
        is_dangerous=True,
    ),
    # Misafir
    P(Perm.GUEST_VIEW, "Misafirleri goruntuleme", "Misafir"),
    P(Perm.GUEST_CREATE, "Misafir kaydi olusturma", "Misafir"),
    P(Perm.GUEST_EDIT, "Misafir kaydi duzenleme", "Misafir"),
    P(Perm.GUEST_DELETE, "Misafir kaydi silme", "Misafir", is_dangerous=True),
    P(
        Perm.GUEST_VIEW_IDENTITY,
        "Kimlik numarasini acik gorme",
        "Misafir",
        "KVKK kapsaminda ozel nitelikli veri; yalnizca gerekli personele verin.",
        is_dangerous=True,
    ),
    P(Perm.GUEST_BLACKLIST, "Kara liste yonetimi", "Misafir", is_dangerous=True),
    P(Perm.GUEST_EXPORT, "Misafir listesi disa aktarma", "Misafir", is_dangerous=True),
    # On buro
    P(Perm.FRONTDESK_CHECKIN, "Giris islemi", "On Buro"),
    P(Perm.FRONTDESK_CHECKOUT, "Cikis islemi", "On Buro"),
    P(Perm.FRONTDESK_EARLY_LATE, "Erken giris / gec cikis onayi", "On Buro"),
    # Folyo / finans
    P(Perm.FOLIO_VIEW, "Folyo goruntuleme", "Finans"),
    P(Perm.FOLIO_POST_CHARGE, "Folyoya ucret isleme", "Finans"),
    P(Perm.FOLIO_VOID_CHARGE, "Ucret gecersiz kilma", "Finans", is_dangerous=True),
    P(Perm.FOLIO_DISCOUNT, "Indirim uygulama", "Finans", is_dangerous=True),
    P(Perm.PAYMENT_VIEW, "Odemeleri goruntuleme", "Finans"),
    P(Perm.PAYMENT_RECEIVE, "Odeme alma", "Finans"),
    P(Perm.PAYMENT_REFUND, "Iade yapma", "Finans", is_dangerous=True),
    P(Perm.INVOICE_VIEW, "Faturalari goruntuleme", "Finans"),
    P(Perm.INVOICE_ISSUE, "Fatura duzenleme", "Finans"),
    P(Perm.FINANCE_VIEW, "Finans modulu erisimi", "Finans"),
    P(Perm.FINANCE_MANAGE, "Gelir/gider kaydi yonetimi", "Finans", is_dangerous=True),
    P(Perm.FINANCE_DAY_CLOSE, "Gun sonu kapanisi", "Finans", is_dangerous=True),
    # Kat hizmetleri
    P(Perm.HOUSEKEEPING_VIEW, "Kat hizmetleri goruntuleme", "Kat Hizmetleri"),
    P(Perm.HOUSEKEEPING_ASSIGN, "Gorev atama", "Kat Hizmetleri"),
    P(Perm.HOUSEKEEPING_COMPLETE, "Gorevi tamamlama", "Kat Hizmetleri"),
    P(Perm.HOUSEKEEPING_INSPECT, "Temizlik kontrolu", "Kat Hizmetleri"),
    P(Perm.LOSTFOUND_MANAGE, "Kayip esya yonetimi", "Kat Hizmetleri"),
    # Teknik servis
    P(Perm.MAINTENANCE_VIEW, "Ariza kayitlarini goruntuleme", "Teknik Servis"),
    P(Perm.MAINTENANCE_CREATE, "Ariza kaydi olusturma", "Teknik Servis"),
    P(Perm.MAINTENANCE_ASSIGN, "Teknisyen atama", "Teknik Servis"),
    P(Perm.MAINTENANCE_RESOLVE, "Arizayi cozme/kapatma", "Teknik Servis"),
    # Personel
    P(Perm.EMPLOYEE_VIEW, "Personeli goruntuleme", "Personel"),
    P(Perm.EMPLOYEE_MANAGE, "Personel yonetimi", "Personel", is_dangerous=True),
    P(Perm.SHIFT_MANAGE, "Vardiya plani yonetimi", "Personel"),
    # Stok
    P(Perm.INVENTORY_VIEW, "Stok goruntuleme", "Stok"),
    P(Perm.INVENTORY_MANAGE, "Stok karti yonetimi", "Stok"),
    P(Perm.INVENTORY_MOVE, "Stok hareketi girisi", "Stok"),
    P(Perm.PURCHASE_VIEW, "Satin alma taleplerini goruntuleme", "Stok"),
    P(Perm.PURCHASE_CREATE, "Satin alma talebi olusturma", "Stok"),
    P(Perm.PURCHASE_APPROVE, "Satin alma talebi onaylama", "Stok", is_dangerous=True),
    # Rapor
    P(Perm.REPORT_VIEW, "Raporlari goruntuleme", "Rapor"),
    P(Perm.REPORT_FINANCIAL, "Mali raporlari goruntuleme", "Rapor", is_dangerous=True),
    P(Perm.REPORT_EXPORT, "Rapor disa aktarma", "Rapor"),
    # Yapay zeka
    P(Perm.AI_USE, "Yapay zeka kullanma", "Yapay Zeka"),
    P(Perm.AI_CONFIGURE, "Saglayici/model yapilandirma", "Yapay Zeka", is_dangerous=True),
    P(
        Perm.AI_APPROVE_ACTION,
        "Yapay zeka eylemini onaylama",
        "Yapay Zeka",
        "Yapay zekanin onerdigi veri degistiren islemi uygulama yetkisi.",
        is_dangerous=True,
    ),
    P(Perm.AI_VIEW_USAGE, "Kullanim ve maliyet raporu", "Yapay Zeka"),
    # Gelistirme merkezi
    P(Perm.DEVCENTER_USE, "Gelistirme merkezini kullanma", "Gelistirme", is_dangerous=True),
    P(
        Perm.DEVCENTER_EXECUTE,
        "Komut calistirma",
        "Gelistirme",
        "Kisitli terminalde onaylanmis komutu calistirir.",
        is_dangerous=True,
    ),
    P(Perm.DEVCENTER_APPLY_PATCH, "Kod degisikligi uygulama", "Gelistirme", is_dangerous=True),
    # Sistem
    P(Perm.USER_VIEW, "Kullanicilari goruntuleme", "Sistem"),
    P(Perm.USER_MANAGE, "Kullanici yonetimi", "Sistem", is_dangerous=True),
    P(Perm.ROLE_MANAGE, "Rol ve yetki yonetimi", "Sistem", is_dangerous=True),
    P(Perm.SETTINGS_VIEW, "Ayarlari goruntuleme", "Sistem"),
    P(Perm.SETTINGS_MANAGE, "Ayarlari degistirme", "Sistem", is_dangerous=True),
    P(Perm.AUDIT_VIEW, "Denetim gunlugu goruntuleme", "Sistem"),
    P(Perm.BACKUP_RUN, "Yedek alma", "Sistem"),
    P(Perm.BACKUP_RESTORE, "Yedekten geri yukleme", "Sistem", is_dangerous=True),
)

#: Kod -> tanim eslemesi (hizli arama icin).
PERMISSION_BY_CODE: dict[str, PermissionSpec] = {p.code: p for p in PERMISSIONS}


# --------------------------------------------------------------------------
#  Varsayilan roller
# --------------------------------------------------------------------------
_FRONTDESK_PERMS = (
    Perm.DASHBOARD_VIEW,
    Perm.PROPERTY_VIEW,
    Perm.ROOM_VIEW,
    Perm.ROOM_STATUS_CHANGE,
    Perm.RATE_VIEW,
    Perm.RESERVATION_VIEW,
    Perm.RESERVATION_CREATE,
    Perm.RESERVATION_EDIT,
    Perm.RESERVATION_CANCEL,
    Perm.GUEST_VIEW,
    Perm.GUEST_CREATE,
    Perm.GUEST_EDIT,
    Perm.FRONTDESK_CHECKIN,
    Perm.FRONTDESK_CHECKOUT,
    Perm.FOLIO_VIEW,
    Perm.FOLIO_POST_CHARGE,
    Perm.PAYMENT_VIEW,
    Perm.PAYMENT_RECEIVE,
    Perm.INVOICE_VIEW,
    Perm.HOUSEKEEPING_VIEW,
    Perm.MAINTENANCE_VIEW,
    Perm.MAINTENANCE_CREATE,
    Perm.REPORT_VIEW,
    Perm.AI_USE,
)

_HOUSEKEEPING_PERMS = (
    Perm.DASHBOARD_VIEW,
    Perm.ROOM_VIEW,
    Perm.ROOM_STATUS_CHANGE,
    Perm.RESERVATION_VIEW,
    Perm.HOUSEKEEPING_VIEW,
    Perm.HOUSEKEEPING_ASSIGN,
    Perm.HOUSEKEEPING_COMPLETE,
    Perm.HOUSEKEEPING_INSPECT,
    Perm.LOSTFOUND_MANAGE,
    Perm.MAINTENANCE_CREATE,
    Perm.MAINTENANCE_VIEW,
    Perm.INVENTORY_VIEW,
    Perm.INVENTORY_MOVE,
    Perm.AI_USE,
)

_MAINTENANCE_PERMS = (
    Perm.DASHBOARD_VIEW,
    Perm.ROOM_VIEW,
    Perm.ROOM_BLOCK,
    Perm.ROOM_STATUS_CHANGE,
    Perm.MAINTENANCE_VIEW,
    Perm.MAINTENANCE_CREATE,
    Perm.MAINTENANCE_ASSIGN,
    Perm.MAINTENANCE_RESOLVE,
    Perm.INVENTORY_VIEW,
    Perm.INVENTORY_MOVE,
    Perm.PURCHASE_VIEW,
    Perm.PURCHASE_CREATE,
    Perm.AI_USE,
)

_ACCOUNTING_PERMS = (
    Perm.DASHBOARD_VIEW,
    Perm.RESERVATION_VIEW,
    Perm.GUEST_VIEW,
    Perm.FOLIO_VIEW,
    Perm.FOLIO_POST_CHARGE,
    Perm.FOLIO_VOID_CHARGE,
    Perm.FOLIO_DISCOUNT,
    Perm.PAYMENT_VIEW,
    Perm.PAYMENT_RECEIVE,
    Perm.PAYMENT_REFUND,
    Perm.INVOICE_VIEW,
    Perm.INVOICE_ISSUE,
    Perm.FINANCE_VIEW,
    Perm.FINANCE_MANAGE,
    Perm.FINANCE_DAY_CLOSE,
    Perm.REPORT_VIEW,
    Perm.REPORT_FINANCIAL,
    Perm.REPORT_EXPORT,
    Perm.PURCHASE_VIEW,
    Perm.PURCHASE_APPROVE,
    Perm.AI_USE,
    Perm.AI_VIEW_USAGE,
)

#: Ilk kurulumda olusturulan roller.
DEFAULT_ROLES: tuple[RoleSpec, ...] = (
    RoleSpec(
        code="admin",
        name="Sistem Yoneticisi",
        description="Tum yetkilere sahiptir. Yalnizca sistem sorumlusuna verilmelidir.",
        permissions=tuple(p.code for p in PERMISSIONS),
    ),
    RoleSpec(
        code="manager",
        name="Otel Muduru",
        description="Gelistirme merkezi ve kullanici yonetimi disindaki tum operasyon yetkileri.",
        permissions=tuple(
            p.code
            for p in PERMISSIONS
            if not p.code.startswith(("devcenter.", "user.", "role.", "backup."))
        ),
    ),
    RoleSpec(
        code="frontdesk",
        name="On Buro Gorevlisi",
        description="Rezervasyon, giris-cikis ve tahsilat islemleri.",
        permissions=_FRONTDESK_PERMS,
    ),
    RoleSpec(
        code="housekeeping",
        name="Kat Hizmetleri",
        description="Oda temizlik gorevleri ve oda durumu yonetimi.",
        permissions=_HOUSEKEEPING_PERMS,
    ),
    RoleSpec(
        code="maintenance",
        name="Teknik Servis",
        description="Ariza kayitlari, bakim ve oda blokeleri.",
        permissions=_MAINTENANCE_PERMS,
    ),
    RoleSpec(
        code="accounting",
        name="Muhasebe",
        description="Folyo, tahsilat, fatura ve mali raporlar.",
        permissions=_ACCOUNTING_PERMS,
    ),
    RoleSpec(
        code="viewer",
        name="Goruntuleyici",
        description="Yalnizca okuma yetkisi; hicbir kayit degistiremez.",
        permissions=(
            Perm.DASHBOARD_VIEW,
            Perm.PROPERTY_VIEW,
            Perm.ROOM_VIEW,
            Perm.RATE_VIEW,
            Perm.RESERVATION_VIEW,
            Perm.GUEST_VIEW,
            Perm.FOLIO_VIEW,
            Perm.HOUSEKEEPING_VIEW,
            Perm.MAINTENANCE_VIEW,
            Perm.INVENTORY_VIEW,
            Perm.REPORT_VIEW,
        ),
    ),
)


def permissions_by_category() -> dict[str, list[PermissionSpec]]:
    """Izinleri kategoriye gore gruplar - rol duzenleme ekrani icin."""
    grouped: dict[str, list[PermissionSpec]] = {}
    for spec in PERMISSIONS:
        grouped.setdefault(spec.category, []).append(spec)
    return grouped


def validate_catalog() -> None:
    """Katalogun tutarliligini dogrular.

    * Izin kodlari benzersiz olmali
    * Rollerin atadigi her izin katalogta bulunmali

    Bu kontrol testlerde ve uygulama acilisinda calisir; boylece bir izin
    yeniden adlandirildiginda role atamasi sessizce kirilmaz.
    """
    codes = [p.code for p in PERMISSIONS]
    duplicates = {c for c in codes if codes.count(c) > 1}
    if duplicates:
        raise ValueError(f"Yinelenen izin kodlari: {sorted(duplicates)}")

    known = set(codes)
    for role in DEFAULT_ROLES:
        unknown = set(role.permissions) - known
        if unknown:
            raise ValueError(
                f"'{role.code}' rolu katalogta olmayan izinler iceriyor: {sorted(unknown)}"
            )


__all__ = [
    "DEFAULT_ROLES",
    "PERMISSIONS",
    "PERMISSION_BY_CODE",
    "Perm",
    "PermissionSpec",
    "RoleSpec",
    "permissions_by_category",
    "validate_catalog",
]
