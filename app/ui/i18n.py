"""Cok dilli metin altyapisi.

Neden Qt'nin kendi ``tr()`` mekanizmasi degil?
---------------------------------------------
Qt Linguist akisi ``.ts`` -> ``lupdate`` -> ``lrelease`` -> ``.qm`` adimlarini
gerektirir ve derleme zinciri ekler. Bu uygulamada metin sayisi yonetilebilir
duzeyde oldugundan, JSON tabanli basit bir sozluk hem daha seffaf hem de
isletmenin kendi terimlerini (or. "folyo" yerine "hesap") duzenleyebilmesi
icin daha erisilebilir. Cevirileri duzenlemek icin derleme gerekmez.

Kullanim::

    from app.ui.i18n import t
    baslik = t("dashboard.title")
    mesaj = t("reservation.created", number="RZV-2026-000042")
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from app.core import paths
from app.core.log import get_logger

log = get_logger(__name__)

#: Desteklenen diller.
SUPPORTED_LANGUAGES: dict[str, str] = {"tr": "Turkce", "en": "English"}

#: Varsayilan dil.
DEFAULT_LANGUAGE = "tr"

_current_language = DEFAULT_LANGUAGE

# --------------------------------------------------------------------------
#  Gomulu ceviriler
# --------------------------------------------------------------------------
# Bu sozluk temel metinleri icerir. Ek/ozel ceviriler
# app/ui/i18n/<dil>.json dosyalarindan yuklenir ve buradakileri EZER;
# boylece isletme kendi terminolojisini kullanabilir.
_BUILTIN: dict[str, dict[str, str]] = {
    "tr": {
        # --- Genel ---
        "app.name": "Akilli Konaklama Yonetim Sistemi",
        "app.short_name": "Konaklama Yonetimi",
        "common.ok": "Tamam",
        "common.cancel": "Iptal",
        "common.save": "Kaydet",
        "common.delete": "Sil",
        "common.edit": "Duzenle",
        "common.add": "Ekle",
        "common.search": "Ara",
        "common.filter": "Filtrele",
        "common.refresh": "Yenile",
        "common.close": "Kapat",
        "common.back": "Geri",
        "common.next": "Ileri",
        "common.finish": "Bitir",
        "common.yes": "Evet",
        "common.no": "Hayir",
        "common.loading": "Yukleniyor...",
        "common.no_data": "Kayit bulunamadi",
        "common.total": "Toplam",
        "common.export": "Disa Aktar",
        "common.print": "Yazdir",
        "common.details": "Ayrintilar",
        "common.confirm": "Onayla",
        "common.warning": "Uyari",
        "common.error": "Hata",
        "common.success": "Basarili",
        # --- Gezinme ---
        "nav.dashboard": "Yonetim Paneli",
        "nav.reservations": "Rezervasyonlar",
        "nav.room_plan": "Oda Plani",
        "nav.frontdesk": "On Buro",
        "nav.guests": "Misafirler",
        "nav.rooms": "Odalar",
        "nav.rates": "Fiyatlar",
        "nav.housekeeping": "Kat Hizmetleri",
        "nav.maintenance": "Teknik Servis",
        "nav.finance": "Finans",
        "nav.inventory": "Stok",
        "nav.staff": "Personel",
        "nav.reports": "Raporlar",
        "nav.ai_center": "Yapay Zeka Merkezi",
        "nav.dev_center": "AI Gelistirme Merkezi",
        "nav.settings": "Ayarlar",
        # --- Panel ---
        "dashboard.title": "Yonetim Paneli",
        "dashboard.occupancy": "Doluluk Orani",
        "dashboard.arrivals": "Bugunku Girisler",
        "dashboard.departures": "Bugunku Cikislar",
        "dashboard.in_house": "Otelde",
        "dashboard.revenue_today": "Gunluk Gelir",
        "dashboard.adr": "Ortalama Oda Fiyati (ADR)",
        "dashboard.revpar": "Oda Basina Gelir (RevPAR)",
        "dashboard.available_rooms": "Bos Oda",
        "dashboard.dirty_rooms": "Kirli Oda",
        "dashboard.out_of_service": "Servis Disi",
        "dashboard.pending_tasks": "Bekleyen Gorev",
        "dashboard.alerts": "Kritik Uyarilar",
        "dashboard.ai_suggestions": "Yapay Zeka Onerileri",
        # --- Rezervasyon ---
        "reservation.title": "Rezervasyonlar",
        "reservation.new": "Yeni Rezervasyon",
        "reservation.number": "Rezervasyon No",
        "reservation.guest": "Misafir",
        "reservation.check_in": "Giris",
        "reservation.check_out": "Cikis",
        "reservation.nights": "Gece",
        "reservation.room": "Oda",
        "reservation.status": "Durum",
        "reservation.source": "Kanal",
        "reservation.total": "Tutar",
        "reservation.balance": "Bakiye",
        "reservation.created": "{number} numarali rezervasyon olusturuldu.",
        "reservation.cancelled": "{number} numarali rezervasyon iptal edildi.",
        "reservation.conflict": "Bu odada secilen tarihlerle cakisan rezervasyon var.",
        # --- On buro ---
        "frontdesk.check_in": "Giris Yap",
        "frontdesk.check_out": "Cikis Yap",
        "frontdesk.early_check_in": "Erken Giris",
        "frontdesk.late_check_out": "Gec Cikis",
        "frontdesk.folio": "Folyo",
        "frontdesk.add_charge": "Ucret Ekle",
        "frontdesk.add_payment": "Odeme Al",
        # --- Oda ---
        "room.number": "Oda No",
        "room.type": "Oda Tipi",
        "room.floor": "Kat",
        "room.status": "Durum",
        "room.clean": "Temiz",
        "room.dirty": "Kirli",
        "room.occupied": "Dolu",
        "room.vacant": "Bos",
        "room.out_of_service": "Servis Disi",
        # --- Yapay zeka ---
        "ai.title": "Yapay Zeka Merkezi",
        "ai.generated_badge": "AI tarafindan olusturuldu",
        "ai.verify_notice": "Yapay zeka ciktilari hata icerebilir. Kritik kararlarda dogrulayin.",
        "ai.provider": "Saglayici",
        "ai.model": "Model",
        "ai.test_connection": "Baglantiyi Test Et",
        "ai.connection_ok": "Baglanti basarili",
        "ai.connection_failed": "Baglanti kurulamadi",
        "ai.approve_action": "Bu islemi onayliyor musunuz?",
        "ai.tokens_used": "Kullanilan jeton",
        "ai.estimated_cost": "Tahmini maliyet",
        # --- Guvenlik ---
        "auth.login": "Giris Yap",
        "auth.logout": "Cikis Yap",
        "auth.username": "Kullanici Adi",
        "auth.password": "Parola",
        "auth.remember": "Beni hatirla",
        "auth.change_password": "Parola Degistir",
        "auth.session_expired": "Oturum sureniz doldu. Lutfen yeniden giris yapin.",
        "auth.no_permission": "Bu islem icin yetkiniz bulunmuyor.",
        # --- Ayarlar ---
        "settings.title": "Ayarlar",
        "settings.general": "Genel",
        "settings.appearance": "Gorunum",
        "settings.theme": "Tema",
        "settings.theme_light": "Acik",
        "settings.theme_dark": "Koyu",
        "settings.theme_system": "Sistem",
        "settings.language": "Dil",
        "settings.ai": "Yapay Zeka",
        "settings.backup": "Yedekleme",
    },
    "en": {
        "app.name": "Smart Hospitality Management System",
        "app.short_name": "Hospitality Manager",
        "common.ok": "OK",
        "common.cancel": "Cancel",
        "common.save": "Save",
        "common.delete": "Delete",
        "common.edit": "Edit",
        "common.add": "Add",
        "common.search": "Search",
        "common.filter": "Filter",
        "common.refresh": "Refresh",
        "common.close": "Close",
        "common.back": "Back",
        "common.next": "Next",
        "common.finish": "Finish",
        "common.yes": "Yes",
        "common.no": "No",
        "common.loading": "Loading...",
        "common.no_data": "No records found",
        "common.total": "Total",
        "common.export": "Export",
        "common.print": "Print",
        "common.details": "Details",
        "common.confirm": "Confirm",
        "common.warning": "Warning",
        "common.error": "Error",
        "common.success": "Success",
        "nav.dashboard": "Dashboard",
        "nav.reservations": "Reservations",
        "nav.room_plan": "Room Plan",
        "nav.frontdesk": "Front Desk",
        "nav.guests": "Guests",
        "nav.rooms": "Rooms",
        "nav.rates": "Rates",
        "nav.housekeeping": "Housekeeping",
        "nav.maintenance": "Maintenance",
        "nav.finance": "Finance",
        "nav.inventory": "Inventory",
        "nav.staff": "Staff",
        "nav.reports": "Reports",
        "nav.ai_center": "AI Center",
        "nav.dev_center": "AI Development Center",
        "nav.settings": "Settings",
        "dashboard.title": "Dashboard",
        "dashboard.occupancy": "Occupancy Rate",
        "dashboard.arrivals": "Today's Arrivals",
        "dashboard.departures": "Today's Departures",
        "dashboard.in_house": "In House",
        "dashboard.revenue_today": "Today's Revenue",
        "dashboard.adr": "Average Daily Rate (ADR)",
        "dashboard.revpar": "Revenue Per Available Room",
        "dashboard.available_rooms": "Available Rooms",
        "dashboard.dirty_rooms": "Dirty Rooms",
        "dashboard.out_of_service": "Out of Service",
        "dashboard.pending_tasks": "Pending Tasks",
        "dashboard.alerts": "Critical Alerts",
        "dashboard.ai_suggestions": "AI Suggestions",
        "reservation.title": "Reservations",
        "reservation.new": "New Reservation",
        "reservation.number": "Confirmation No",
        "reservation.guest": "Guest",
        "reservation.check_in": "Check-in",
        "reservation.check_out": "Check-out",
        "reservation.nights": "Nights",
        "reservation.room": "Room",
        "reservation.status": "Status",
        "reservation.source": "Channel",
        "reservation.total": "Amount",
        "reservation.balance": "Balance",
        "reservation.created": "Reservation {number} created.",
        "reservation.cancelled": "Reservation {number} cancelled.",
        "reservation.conflict": "This room has a conflicting reservation for the selected dates.",
        "frontdesk.check_in": "Check In",
        "frontdesk.check_out": "Check Out",
        "frontdesk.early_check_in": "Early Check-in",
        "frontdesk.late_check_out": "Late Check-out",
        "frontdesk.folio": "Folio",
        "frontdesk.add_charge": "Add Charge",
        "frontdesk.add_payment": "Add Payment",
        "room.number": "Room No",
        "room.type": "Room Type",
        "room.floor": "Floor",
        "room.status": "Status",
        "room.clean": "Clean",
        "room.dirty": "Dirty",
        "room.occupied": "Occupied",
        "room.vacant": "Vacant",
        "room.out_of_service": "Out of Service",
        "ai.title": "AI Center",
        "ai.generated_badge": "AI generated",
        "ai.verify_notice": "AI output may contain errors. Verify before critical decisions.",
        "ai.provider": "Provider",
        "ai.model": "Model",
        "ai.test_connection": "Test Connection",
        "ai.connection_ok": "Connection successful",
        "ai.connection_failed": "Connection failed",
        "ai.approve_action": "Do you approve this action?",
        "ai.tokens_used": "Tokens used",
        "ai.estimated_cost": "Estimated cost",
        "auth.login": "Sign In",
        "auth.logout": "Sign Out",
        "auth.username": "Username",
        "auth.password": "Password",
        "auth.remember": "Remember me",
        "auth.change_password": "Change Password",
        "auth.session_expired": "Your session has expired. Please sign in again.",
        "auth.no_permission": "You do not have permission for this action.",
        "settings.title": "Settings",
        "settings.general": "General",
        "settings.appearance": "Appearance",
        "settings.theme": "Theme",
        "settings.theme_light": "Light",
        "settings.theme_dark": "Dark",
        "settings.theme_system": "System",
        "settings.language": "Language",
        "settings.ai": "AI",
        "settings.backup": "Backup",
    },
}


@lru_cache(maxsize=8)
def _load_translations(language: str) -> dict[str, str]:
    """Gomulu cevirileri yukler ve varsa JSON dosyasiyla gunceller."""
    translations = dict(_BUILTIN.get(language, {}))

    override_file = paths.I18N_DIR / f"{language}.json"
    if override_file.exists():
        try:
            data = json.loads(override_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                translations.update({str(k): str(v) for k, v in data.items()})
                log.debug("ceviri_dosyasi_yuklendi", language=language, count=len(data))
        except (OSError, json.JSONDecodeError) as exc:
            # Bozuk ceviri dosyasi uygulamayi durdurmamali.
            log.warning("ceviri_dosyasi_okunamadi", language=language, error=str(exc))

    return translations


def set_language(language: str) -> None:
    """Etkin dili degistirir."""
    global _current_language
    if language not in SUPPORTED_LANGUAGES:
        log.warning("desteklenmeyen_dil", language=language, fallback=DEFAULT_LANGUAGE)
        language = DEFAULT_LANGUAGE
    _current_language = language


def get_language() -> str:
    """Etkin dili dondurur."""
    return _current_language


def t(key: str, /, **kwargs: Any) -> str:
    """Anahtara karsilik gelen metni dondurur.

    Anahtar bulunamazsa **anahtarin kendisi** dondurulur ve uyari loglanir.
    Bu bilincli bir tercih: eksik ceviri yuzunden arayuzde bos alan kalmasi,
    anahtar adinin gorunmesinden daha kotudur (kullanici ne oldugunu anlamaz,
    gelistirici de fark etmez).

    >>> t("common.ok")
    'Tamam'
    >>> t("boyle.bir.anahtar.yok")
    'boyle.bir.anahtar.yok'
    """
    translations = _load_translations(_current_language)
    text = translations.get(key)

    if text is None and _current_language != DEFAULT_LANGUAGE:
        text = _load_translations(DEFAULT_LANGUAGE).get(key)

    if text is None:
        log.debug("ceviri_bulunamadi", key=key, language=_current_language)
        return key

    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError) as exc:
            # Bicimlendirme hatasi arayuzu cokertmemeli.
            log.warning("ceviri_bicimlendirme_hatasi", key=key, error=str(exc))
            return text

    return text


def available_languages() -> dict[str, str]:
    """Kod -> gorunen ad eslemesi."""
    return dict(SUPPORTED_LANGUAGES)


def clear_cache() -> None:
    """Ceviri onbellegini temizler (ceviri dosyasi duzenlendiginde)."""
    _load_translations.cache_clear()


__all__ = [
    "DEFAULT_LANGUAGE",
    "SUPPORTED_LANGUAGES",
    "available_languages",
    "clear_cache",
    "get_language",
    "set_language",
    "t",
]
