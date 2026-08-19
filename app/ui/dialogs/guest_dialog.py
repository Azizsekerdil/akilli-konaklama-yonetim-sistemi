"""Misafir olusturma / duzenleme diyalogu.

Kisisel veri yaklasimi
----------------------
Kimlik numarasi alani **duzenleme kipinde bos gelir**. Mevcut numarayi
diyaloga yazdirmak, kaydi acan her personelin numarayi gormesi demekti; oysa
acik goruntuleme ayri bir yetkiye baglidir (bkz.
:meth:`app.application.services.guest_service.GuestService.reveal_identity`).
Alan bos birakilirsa kayitli numara **degistirilmez**.

Mukerrer kayit uyarisi
----------------------
Ayni ad+soyad veya ayni e-posta bulundugunda kullanici uyarilir ama kayit
**engellenmez**: ayni isimde iki farkli misafir gercekten olabilir. Engellemek,
gercek bir misafirin sisteme girilememesine yol acardi.
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.application.services.guest_service import GuestService, GuestSummary
from app.core.exceptions import HotelError, ValidationError
from app.core.log import get_logger
from app.domain.enums import GuestTitle, IdentityDocumentType, VIPLevel
from app.ui.i18n import t
from app.ui.session import UiSession
from app.ui.widgets.common import show_error

log = get_logger(__name__)

#: Dogum tarihi alaninin "belirtilmedi" degeri.
_UNSET_BIRTH_DATE = QDate(1900, 1, 1)

#: Misafirin tercih ettigi dil icin secenek katalogu.
#:
#: Burada :data:`app.ui.i18n.SUPPORTED_LANGUAGES` KULLANILMAZ. O sozluk
#: **arayuzun** konusabildigi dilleri listeler (``tr``, ``en``) - misafirin
#: konustugu dil ise bagimsizdir; Almanca konusan bir misafir, arayuz Almanca
#: olmadan da kayda gecebilmelidir. Demo veride 60 misafirin 17'si ``de``
#: veya ``ru`` konusuyor: iki secenekli bir liste bu kayitlari temsil edemez
#: ve kaydetme sirasinda dilleri sessizce ``tr``ye cevirirdi.
#:
#: Etiketler Turkce yazilir; ``SUPPORTED_LANGUAGES`` her dili kendi dilinde
#: adlandirir ("English") ve Turkce bir formda yabanci gorunurdu.
GUEST_LANGUAGES: dict[str, str] = {
    "tr": "Turkce",
    "en": "Ingilizce",
    "de": "Almanca",
    "fr": "Fransizca",
    "ru": "Rusca",
    "ar": "Arapca",
    "es": "Ispanyolca",
    "it": "Italyanca",
    "nl": "Felemenkce",
}


def guest_language_label(code: str | None) -> str:
    """Dil kodunu okunur ada cevirir; taninmayan kod buyuk harfle gosterilir."""
    if not code:
        return "-"
    return GUEST_LANGUAGES.get(code.lower(), code.upper())


class GuestDialog(QDialog):
    """Misafir kaydi formu.

    Kullanim::

        dialog = GuestDialog(ui_session, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            summary = dialog.result_summary
    """

    def __init__(
        self,
        ui_session: UiSession,
        *,
        guest_id: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.ui = ui_session
        self.guest_id = guest_id
        self.result_summary: GuestSummary | None = None

        self.setWindowTitle("Misafir Duzenle" if guest_id else "Yeni Misafir")
        self.setMinimumWidth(620)

        self._build()
        if guest_id is not None:
            self._load_guest(guest_id)

    # ----------------------------------------------------------------- #
    #  Kurulum
    # ----------------------------------------------------------------- #
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        columns = QHBoxLayout()
        columns.setSpacing(14)
        columns.addWidget(self._build_identity_group(), 1)
        columns.addWidget(self._build_contact_group(), 1)
        root.addLayout(columns)

        # KVKK aciklamasi dar form sutununda degil, tam genislikte durur:
        # sutun icinde satir kaydirmali metnin son satiri kirpiliyordu.
        self._identity_hint = QLabel(
            "KVKK: Kimlik numarasi veritabaninda sifreli saklanir, loglara ve "
            "disa aktarmalara duz metin olarak yazilmaz."
        )
        self._identity_hint.setObjectName("Muted")
        self._identity_hint.setWordWrap(True)
        root.addWidget(self._identity_hint)

        # --- Mukerrer kayit uyarisi ---
        self._duplicate_label = QLabel()
        self._duplicate_label.setObjectName("BadgeWarning")
        self._duplicate_label.setWordWrap(True)
        self._duplicate_label.setVisible(False)
        root.addWidget(self._duplicate_label)

        # --- Dugmeler ---
        buttons = QHBoxLayout()
        buttons.addStretch(1)

        cancel = QPushButton(t("common.cancel"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)

        self._save_button = QPushButton(t("common.save"))
        self._save_button.setObjectName("Primary")
        self._save_button.setDefault(True)
        self._save_button.clicked.connect(self._save)
        buttons.addWidget(self._save_button)

        root.addLayout(buttons)

    def _build_identity_group(self) -> QGroupBox:
        box = QGroupBox("Kimlik Bilgileri")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setSpacing(8)

        self._title = QComboBox()
        for value, label in GuestTitle.choices():
            self._title.addItem(label, value)
        form.addRow("Hitap", self._title)

        self._first_name = QLineEdit()
        self._first_name.setMaxLength(80)
        self._first_name.editingFinished.connect(self._check_duplicates)
        form.addRow("Ad *", self._first_name)

        self._last_name = QLineEdit()
        self._last_name.setMaxLength(80)
        self._last_name.editingFinished.connect(self._check_duplicates)
        form.addRow("Soyad *", self._last_name)

        self._birth_date = QDateEdit()
        self._birth_date.setCalendarPopup(True)
        self._birth_date.setDisplayFormat("dd.MM.yyyy")
        self._birth_date.setMinimumDate(_UNSET_BIRTH_DATE)
        self._birth_date.setMaximumDate(QDate.currentDate())
        # En kucuk deger "belirtilmedi" anlamina gelir; boylece dogum tarihi
        # bilinmeyen misafir icin uydurma bir tarih girilmek zorunda kalinmaz.
        self._birth_date.setSpecialValueText("Belirtilmedi")
        self._birth_date.setDate(_UNSET_BIRTH_DATE)
        form.addRow("Dogum Tarihi", self._birth_date)

        self._nationality = QLineEdit("Turkiye")
        form.addRow("Uyruk", self._nationality)

        self._identity_type = QComboBox()
        for value, label in IdentityDocumentType.choices():
            self._identity_type.addItem(label, value)
        form.addRow("Kimlik Turu", self._identity_type)

        self._identity_number = QLineEdit()
        self._identity_number.setMaxLength(40)
        form.addRow("Kimlik No", self._identity_number)

        return box

    def _build_contact_group(self) -> QGroupBox:
        box = QGroupBox("Iletisim ve Tercihler")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setSpacing(8)

        self._email = QLineEdit()
        self._email.setMaxLength(200)
        self._email.setPlaceholderText("ornek@eposta.com")
        self._email.editingFinished.connect(self._check_duplicates)
        form.addRow("E-posta", self._email)

        self._phone = QLineEdit()
        self._phone.setMaxLength(40)
        self._phone.setPlaceholderText("+90 ...")
        form.addRow("Telefon", self._phone)

        self._mobile = QLineEdit()
        self._mobile.setMaxLength(40)
        form.addRow("Cep Telefonu", self._mobile)

        self._address = QLineEdit()
        self._address.setMaxLength(300)
        form.addRow("Adres", self._address)

        self._city = QLineEdit()
        self._city.setMaxLength(100)
        form.addRow("Sehir", self._city)

        self._country = QLineEdit("Turkiye")
        form.addRow("Ulke", self._country)

        self._vip_level = QComboBox()
        for value, label in VIPLevel.choices():
            self._vip_level.addItem(label, value)
        form.addRow("VIP Seviyesi", self._vip_level)

        self._language = QComboBox()
        for code, label in GUEST_LANGUAGES.items():
            self._language.addItem(label, code)
        form.addRow("Dil Tercihi", self._language)

        return box

    # ----------------------------------------------------------------- #
    #  Veri
    # ----------------------------------------------------------------- #
    def _load_guest(self, guest_id: int) -> None:
        """Mevcut kaydi forma doldurur."""
        try:
            with self.ui.service_context(commit=False) as ctx:
                profile = GuestService(ctx).get_profile(guest_id)
        except HotelError as exc:
            show_error(self, exc)
            return

        self._select_by_data(self._title, profile.title_value)
        self._first_name.setText(profile.first_name)
        self._last_name.setText(profile.last_name)
        if profile.birth_date is not None:
            self._birth_date.setDate(
                QDate(profile.birth_date.year, profile.birth_date.month, profile.birth_date.day)
            )
        self._nationality.setText(profile.nationality)
        self._select_by_data(self._identity_type, profile.identity_document_value)

        # Kimlik numarasi bilerek doldurulmaz - bkz. modul aciklamasi.
        self._identity_number.clear()
        if profile.has_identity:
            # Kisa tutuluyor: alan dar, uzun ipucu metni kirpiliyordu. Ayrinti
            # tam genislikteki KVKK aciklamasinda yazili.
            self._identity_number.setPlaceholderText(f"Kayitli: {profile.identity_masked}")
            self._identity_hint.setText(
                "KVKK: Kimlik numarasi sifreli saklanir. Alan bos birakilirsa kayitli "
                "numara DEGISMEZ; yeni bir numara yazarsaniz eskisinin uzerine yazilir."
            )

        self._email.setText(profile.summary.email or "")
        self._phone.setText(profile.summary.phone or "")
        self._mobile.setText(profile.mobile or "")
        self._address.setText(profile.address_line or "")
        self._city.setText(profile.city or "")
        self._country.setText(profile.country or "Turkiye")
        self._select_by_data(self._vip_level, profile.summary.vip_level_value)
        self._select_language(profile.preferred_language)

        # ``setText`` imleci metnin SONUNA birakir; alandan uzun bir deger
        # (e-posta, adres) bastan kirpilmis gorunur - kullanici formu acinca
        # "nbakli044@ornek-test.local" gibi bozuk bir metin gorurdu. Imleci
        # basa almak degeri bastan gosterir.
        for field in (
            self._first_name,
            self._last_name,
            self._nationality,
            self._email,
            self._phone,
            self._mobile,
            self._address,
            self._city,
            self._country,
        ):
            field.setCursorPosition(0)

    def _select_language(self, code: str | None) -> None:
        """Dil secimini ayarlar; katalogda olmayan kodu KAYBETMEZ.

        Taninmayan bir kod icin sessizce ilk siradaki dile dusmek, kaydetme
        sirasinda misafirin dilini fark ettirmeden degistirirdi. Bunun yerine
        kod listeye eklenir ve secilir; boylece kullanici bilerek degistirmedigi
        surece deger korunur.
        """
        cleaned = (code or "").strip().lower()
        if not cleaned:
            return
        index = self._language.findData(cleaned)
        if index < 0:
            self._language.addItem(guest_language_label(cleaned), cleaned)
            index = self._language.count() - 1
        self._language.setCurrentIndex(index)

    @staticmethod
    def _select_by_data(combo: QComboBox, value: str | None) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _birth_date_value(self) -> date | None:
        selected = self._birth_date.date()
        if selected == _UNSET_BIRTH_DATE:
            return None
        return selected.toPython()

    def _form_values(self) -> dict[str, object]:
        """Formdaki degerleri servis imzasina uygun sozluge cevirir."""
        return {
            "title": GuestTitle(self._title.currentData()),
            "first_name": self._first_name.text().strip(),
            "last_name": self._last_name.text().strip(),
            "birth_date": self._birth_date_value(),
            "nationality": self._nationality.text().strip() or "Turkiye",
            "preferred_language": self._language.currentData() or "tr",
            "identity_document_type": IdentityDocumentType(self._identity_type.currentData()),
            "email": self._email.text().strip() or None,
            "phone": self._phone.text().strip() or None,
            "mobile": self._mobile.text().strip() or None,
            "address_line": self._address.text().strip() or None,
            "city": self._city.text().strip() or None,
            "country": self._country.text().strip() or "Turkiye",
            "vip_level": VIPLevel(self._vip_level.currentData()),
        }

    # ----------------------------------------------------------------- #
    #  Mukerrer kayit
    # ----------------------------------------------------------------- #
    def _check_duplicates(self) -> list[GuestSummary]:
        """Olasi mukerrer kayitlari bulur ve uyari satirini gunceller."""
        first = self._first_name.text().strip()
        last = self._last_name.text().strip()
        email = self._email.text().strip() or None
        if not (first and last) and not email:
            self._duplicate_label.setVisible(False)
            return []

        try:
            with self.ui.service_context(commit=False) as ctx:
                matches = GuestService(ctx).find_possible_duplicates(
                    first_name=first,
                    last_name=last,
                    email=email,
                    exclude_guest_id=self.guest_id,
                )
        except HotelError as exc:
            # Uyari mekanizmasi calismazsa form kullanilabilir kalmalidir.
            log.warning("mukerrer_kontrolu_basarisiz", code=exc.code, detail=exc.detail)
            self._duplicate_label.setVisible(False)
            return []

        if not matches:
            self._duplicate_label.setVisible(False)
            return []

        names = ", ".join(match.full_name for match in matches[:3])
        extra = f" ve {len(matches) - 3} kayit daha" if len(matches) > 3 else ""
        self._duplicate_label.setText(
            f"Benzer kayit bulundu: {names}{extra}. "
            "Ayni kisi olabilir - kaydetmeden once kontrol edin."
        )
        self._duplicate_label.setVisible(True)
        return matches

    # ----------------------------------------------------------------- #
    #  Kayit
    # ----------------------------------------------------------------- #
    def _save(self) -> None:
        values = self._form_values()
        if not values["first_name"] or not values["last_name"]:
            show_error(
                self,
                ValidationError("Ad ve soyad alanlari zorunludur.", field="first_name"),
                title=t("common.warning"),
            )
            return

        matches = self._check_duplicates()
        if matches:
            from app.ui.widgets.common import confirm

            if not confirm(
                self,
                f"Benzer {len(matches)} kayit bulundu. Yeni bir kayit olusturulsun mu?",
                detail="Ayni kisiyse mevcut kaydi duzenlemeniz onerilir.",
                title=t("common.warning"),
            ):
                return

        identity = self._identity_number.text().strip()

        try:
            with self.ui.service_context() as ctx:
                service = GuestService(ctx)
                if self.guest_id is None:
                    self.result_summary = service.create(
                        identity_number=identity or None,
                        **values,  # type: ignore[arg-type]
                    )
                else:
                    changes = dict(values)
                    # Bos kimlik alani "degistirme" demektir, "sil" demek degil.
                    if identity:
                        changes["identity_number"] = identity
                    self.result_summary = service.update(self.guest_id, **changes)
        except HotelError as exc:
            show_error(self, exc)
            return

        self.accept()


__all__ = ["GuestDialog"]
