"""Misafirler ekrani: arama, liste ve secili misafirin tam profili.

Ekran ikiye bolunmustur. Solda arama ve liste, sagda secili misafirin
sekmeli profili yer alir. Bu duzen bilinclidir: resepsiyon gorevlisi
telefonda konusurken hem listeyi hem profili ayni anda gormek zorundadir;
ayri bir "detay ekrani" her seferinde geri donmeyi gerektirirdi.

Kisisel veri
------------
Kimlik numarasi ekranda **her zaman maskeli** durur. "Goster" dugmesi
yalnizca :data:`~app.security.permissions.Perm.GUEST_VIEW_IDENTITY` iznine
sahip kullanicida etkindir ve tiklamadan once kullaniciya, bu islemin
denetim gunlugune yazilacagi acikca bildirilir.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.application.services.guest_service import (
    ConsentEntry,
    GuestProfile,
    GuestService,
    GuestSummary,
    NoteEntry,
    StayHistoryEntry,
)
from app.core.exceptions import HotelError
from app.core.log import get_logger
from app.domain.enums import ConsentType
from app.security.permissions import Perm

# Dil katalogu diyalog modulunde tanimlidir: secenekleri SUNAN bilesen orasi.
# Profil ile duzenleme formunun ayni adlandirmayi kullanmasi sarttir; iki ayri
# liste tutuldugunda profil "Ingilizce", form "English" gosteriyordu.
from app.ui.dialogs.guest_dialog import GuestDialog, guest_language_label
from app.ui.formatting import format_date, format_datetime, format_number, format_short_date
from app.ui.i18n import t
from app.ui.pages.base import BasePage
from app.ui.theme import active_palette
from app.ui.widgets.common import (
    Card,
    EmptyState,
    SearchBox,
    SectionTitle,
    StatusBadge,
    ToastLevel,
    confirm,
    show_error,
    show_toast,
)
from app.ui.widgets.table import Column, FilterableTableView

log = get_logger(__name__)


class GuestsPage(BasePage):
    """Misafir CRM ekrani."""

    required_permission = Perm.GUEST_VIEW
    title = "Misafirler"
    icon = "\U0001f465"

    #: Listede gosterilecek en fazla kayit. Arama sunucu tarafinda yapilir;
    #: tum misafir tabanini ceken bir liste buyuk otellerde ekrani kilitlerdi.
    LIST_LIMIT = 200

    # ----------------------------------------------------------------- #
    #  Kurulum
    # ----------------------------------------------------------------- #
    def build(self) -> None:
        self._query = ""
        self._selected_guest_id: int | None = None
        self._profile: GuestProfile | None = None

        self.root_layout.addLayout(self._build_header())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_list_panel())
        splitter.addWidget(self._build_profile_panel())
        # Liste alti sutun tasir; profil ise tek sutunlu bir formdur. Bu yuzden
        # sol panele biraz daha fazla genislik verilir - aksi halde ad sutunu
        # kirpilir ve kullanici kimi sectigini goremez.
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([740, 470])
        self.root_layout.addWidget(splitter, 1)

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()

        header.addWidget(SectionTitle(t("nav.guests")))
        self._count_label = QLabel("-")
        self._count_label.setObjectName("Muted")
        header.addWidget(self._count_label)
        header.addStretch(1)

        self._new_button = QPushButton("Yeni Misafir")
        self._new_button.setObjectName("Primary")
        self._new_button.clicked.connect(self._create_guest)
        # Yetki kontrolu arayuzde de yapilir; servis katmani zaten reddeder,
        # ancak tiklanabilir bir dugme sunup hata gostermek kotu deneyimdir.
        self._new_button.setEnabled(self.ui.can(Perm.GUEST_CREATE))
        if not self._new_button.isEnabled():
            self._new_button.setToolTip(t("auth.no_permission"))
        header.addWidget(self._new_button)

        refresh = QPushButton(t("common.refresh"))
        refresh.clicked.connect(lambda: self.refresh(force=True))
        header.addWidget(refresh)

        return header

    def _build_list_panel(self) -> QWidget:
        card = Card("Misafir Listesi", self)

        # SearchBox gecikmeli sinyal yayar: her tus vurusunda sunucu tarafi
        # arama calistirmak buyuk misafir tabanlarinda ekrani kilitlerdi.
        self._search = SearchBox("Ad, soyad, e-posta veya telefon ile ara", parent=self)
        self._search.search_triggered.connect(lambda _text: self._apply_search())
        self._search.returnPressed.connect(self._apply_search)
        card.add_widget(self._search)

        # Genisleyen sutun ad degil E-POSTA: ad sutunu kara liste isaretini de
        # tasidigi icin sabit ve yeterli genislikte olmalidir; e-posta ise
        # kirpilsa bile profil panelinde tam haliyle gorunur.
        #
        # Sabit genislikler render edilerek olculdu ve DARALTILMAMALIDIR.
        # Bir denemede hepsi 8-10 piksel kisildi ki e-posta sutunu genislesin;
        # sonuc daha kotuydu - telefon "+90 555 000 00 ...", VIP "Stand..." ve
        # "Konaklama" basligi kirpildi. Yani bes sutun birden bozuldu, kazanan
        # tek sutun oldu. E-postanin uzun adreslerde kirpilmasi kabul edilen
        # bedeldir: tam deger profil panelinde gorunur.
        self._table = FilterableTableView(
            [
                Column(
                    "full_name",
                    "Ad Soyad",
                    getter=self._name_cell,
                    width=185,
                    color_getter=self._name_color,
                ),
                Column("phone", "Telefon", width=132),
                Column("email", "E-posta", stretch=True),
                Column("vip_level", "VIP", width=76),
                Column("total_stays", "Konaklama", width=84),
                Column(
                    "last_stay_date",
                    "Son Ziyaret",
                    formatter=format_short_date,
                    width=94,
                ),
            ],
            parent=self,
        )
        # Ada gore artan siralama; varsayilan davranis azalan siralamayla
        # aciliyor ve liste ters alfabetik gorunuyordu.
        self._table.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._table.selection_changed.connect(self._on_selection_changed)
        self._table.row_activated.connect(lambda _row: self._edit_guest())

        # Iki ayri bos durum: "hic kayit yok" ile "arama sonucsuz" farkli
        # sorunlardir ve kullaniciyi farkli eyleme yonlendirir.
        self._list_stack = QStackedWidget()
        self._list_stack.addWidget(self._table)
        self._list_stack.addWidget(
            EmptyState(
                "Arama olcutune uyan misafir bulunamadi.",
                hint="Farkli bir ad, e-posta veya telefon deneyin.",
                icon="\U0001f50d",
                parent=self,
            )
        )
        self._list_stack.addWidget(
            EmptyState(
                "Henuz kayitli misafir yok.",
                hint="'Yeni Misafir' dugmesiyle ilk kaydi olusturabilirsiniz.",
                icon="\U0001f465",
                parent=self,
            )
        )
        card.add_widget(self._list_stack)

        return card

    def _build_profile_panel(self) -> QWidget:
        self._profile_stack = QStackedWidget()
        self._profile_stack.addWidget(
            EmptyState(
                "Soldaki listeden bir misafir secin.",
                hint="Profil, konaklama gecmisi ve KVKK izinleri burada gorunur.",
                icon="\U0001f464",
                parent=self,
            )
        )

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addLayout(self._build_profile_header())

        # Sekme basliklari kisa tutuldu: profil paneli dar oldugundan uzun
        # basliklar sekme cubugunu tasirip kaydirma oklari cikariyordu.
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_general_tab(), "Genel")
        self._tabs.addTab(self._build_stays_tab(), "Konaklamalar")
        self._tabs.addTab(self._build_notes_tab(), "Tercih ve Not")
        self._tabs.addTab(self._build_consents_tab(), "KVKK")
        self._tabs.setTabToolTip(1, "Konaklama gecmisi")
        self._tabs.setTabToolTip(2, "Tercihler ve personel notlari")
        self._tabs.setTabToolTip(3, "KVKK acik riza kayitlari")
        layout.addWidget(self._tabs, 1)

        self._profile_stack.addWidget(container)
        return self._profile_stack

    def _build_profile_header(self) -> QVBoxLayout:
        wrapper = QVBoxLayout()
        wrapper.setSpacing(6)

        top = QHBoxLayout()
        self._profile_name = QLabel("-")
        self._profile_name.setObjectName("SectionTitle")
        top.addWidget(self._profile_name)
        top.addStretch(1)

        self._edit_button = QPushButton(t("common.edit"))
        self._edit_button.clicked.connect(self._edit_guest)
        self._edit_button.setEnabled(self.ui.can(Perm.GUEST_EDIT))
        if not self._edit_button.isEnabled():
            self._edit_button.setToolTip(t("auth.no_permission"))
        top.addWidget(self._edit_button)

        self._blacklist_button = QPushButton("Kara Liste")
        self._blacklist_button.clicked.connect(self._toggle_blacklist)
        self._blacklist_button.setEnabled(self.ui.can(Perm.GUEST_BLACKLIST))
        if not self._blacklist_button.isEnabled():
            self._blacklist_button.setToolTip(t("auth.no_permission"))
        top.addWidget(self._blacklist_button)

        wrapper.addLayout(top)

        # Rozetler ad satirinda DEGIL, altinda kendi satirindadir. Ad, iki
        # dugme ve uc rozet yan yana konuldugunda sag panelin en kucuk
        # genisligi 491 piksele ciktiginda bolucu, listeden yer calmak zorunda
        # kaliyordu; e-posta sutunu bunun bedelini oduyordu. Ayri satir hem bu
        # baskiyi kaldirir hem de uzun adlarin rozetleri itmesini onler.
        badges = QHBoxLayout()
        badges.setSpacing(6)

        self._vip_badge = StatusBadge("Standart", "info")
        self._vip_badge.setVisible(False)
        badges.addWidget(self._vip_badge)

        self._blacklist_badge = StatusBadge("KARA LISTE", "danger")
        self._blacklist_badge.setVisible(False)
        badges.addWidget(self._blacklist_badge)

        # Listede "!" oneki ile isaretlenen misafirin profilinde de gorunur bir
        # karsiligi olmalidir. Aksi halde kullanici satirin neden isaretli
        # oldugunu anlamak icin sekmeleri tek tek gezmek zorunda kalir; isaret
        # yalnizca listede kalirsa profil, uyarinin varligini gizlemis olur.
        self._alert_badge = StatusBadge("UYARI NOTU", "warning")
        self._alert_badge.setToolTip("Ayrinti icin 'Tercih ve Not' sekmesine bakin.")
        self._alert_badge.setVisible(False)
        badges.addWidget(self._alert_badge)

        badges.addStretch(1)
        wrapper.addLayout(badges)

        self._blacklist_reason = QLabel()
        self._blacklist_reason.setObjectName("BadgeDanger")
        self._blacklist_reason.setWordWrap(True)
        self._blacklist_reason.setVisible(False)
        wrapper.addWidget(self._blacklist_reason)

        return wrapper

    # ---------------- Sekme: Genel ----------------
    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(10)

        # Etiket-deger ciftleri icin QFormLayout kullaniliyor: iki sutunlu bir
        # izgarada uzun bir deger (or. "22 Temmuz 1967 (59 yasinda)") satir
        # yuksekligini buyutuyor ve komsu sutunda bos bosluk birakiyordu.
        info_card = Card("Iletisim ve Profil", self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(6)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self._general_fields: dict[str, QLabel] = {}
        for key, label in (
            ("email", "E-posta"),
            ("phone", "Telefon"),
            ("mobile", "Cep Telefonu"),
            ("birth_date", "Dogum Tarihi"),
            ("nationality", "Uyruk"),
            ("language", "Dil Tercihi"),
            ("address", "Adres"),
            ("city", "Sehir / Ulke"),
            ("vip", "VIP Seviyesi"),
            ("company", "Kurumsal Musteri"),
            ("agency", "Acente"),
            ("stats", "Konaklama Ozeti"),
        ):
            caption = QLabel(label)
            caption.setObjectName("Muted")
            value = QLabel("-")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(caption, value)
            self._general_fields[key] = value

        info_card.add_layout(form)
        outer.addWidget(info_card)

        # --- Kimlik satiri ---
        identity_card = Card("Kimlik Bilgisi", self)

        identity_row = QHBoxLayout()
        self._identity_type_label = QLabel("-")
        self._identity_type_label.setObjectName("Muted")
        identity_row.addWidget(self._identity_type_label)

        self._identity_value = QLabel("-")
        self._identity_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        identity_row.addWidget(self._identity_value)
        identity_row.addStretch(1)

        self._reveal_button = QPushButton("Goster")
        self._reveal_button.clicked.connect(self._reveal_identity)
        can_reveal = self.ui.can(Perm.GUEST_VIEW_IDENTITY)
        self._reveal_button.setEnabled(can_reveal)
        self._reveal_button.setToolTip(
            "Acik goruntuleme denetim gunlugune kaydedilir."
            if can_reveal
            else "Kimlik numarasini acik gormek icin ayri yetki gerekir."
        )
        identity_row.addWidget(self._reveal_button)
        identity_card.add_layout(identity_row)

        note = QLabel(
            "KVKK: Kimlik numarasi sifreli saklanir. Acik her goruntuleme "
            "kullanici adi ve zaman damgasiyla denetim gunlugune yazilir."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        identity_card.add_widget(note)

        outer.addWidget(identity_card)
        outer.addStretch(1)
        # Bu sekme QScrollArea icine ALINMAZ: kaydirma alani, satir kaydirmali
        # (word wrap) etiketlerin yukseklik-genislik iliskisini tasimaz ve uzun
        # e-posta/adres degerleri tek satirda kirpilir.
        return page

    # ---------------- Sekme: Konaklama gecmisi ----------------
    def _build_stays_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)

        self._stays_table = FilterableTableView(
            [
                # Cikis tarihi ayri sutun DEGIL: dar profil panelinde alti
                # sutun sigmiyor ve yatay kaydirma cubugu cikiyordu. Cikis
                # tarihi giris + gece sayisindan turetilebilir; bu yuzden
                # feda edilen sutun odur.
                Column("check_in", "Giris", formatter=format_short_date, width=92),
                Column("room_number", "Oda", width=58),
                Column("nights", "Gece", width=52),
                Column("amount", "Tutar", width=95),
                Column("status", "Durum", stretch=True),
            ],
            parent=self,
        )
        self._stays_table.setMinimumHeight(220)
        self._stays_stack = QStackedWidget()
        self._stays_stack.addWidget(self._stays_table)
        self._stays_stack.addWidget(
            EmptyState(
                "Bu misafirin kayitli konaklamasi yok.",
                hint="Ilk rezervasyon olusturuldugunda burada gorunecek.",
                icon="\U0001f6cf",
                parent=self,
            )
        )
        layout.addWidget(self._stays_stack)
        return page

    # ---------------- Sekme: Tercihler ve notlar ----------------
    def _build_notes_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self._add_note_button = QPushButton("Not Ekle")
        self._add_note_button.clicked.connect(self._add_note)
        self._add_note_button.setEnabled(self.ui.can(Perm.GUEST_EDIT))
        if not self._add_note_button.isEnabled():
            self._add_note_button.setToolTip(t("auth.no_permission"))
        actions.addWidget(self._add_note_button)
        layout.addLayout(actions)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        holder = QWidget()
        self._notes_body = QVBoxLayout(holder)
        self._notes_body.setContentsMargins(0, 0, 0, 0)
        self._notes_body.setSpacing(10)
        scroll.setWidget(holder)
        layout.addWidget(scroll, 1)

        return page

    # ---------------- Sekme: KVKK ----------------
    def _build_consents_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        info = QLabel(
            "Izinler uzerine yazilmaz: her verme ve geri alma ayri bir satir olarak "
            "saklanir. Boylece hangi izin hangi tarihte alindi/geri alindi sorusu "
            "denetimde yanitlanabilir."
        )
        info.setObjectName("Muted")
        info.setWordWrap(True)
        layout.addWidget(info)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self._consent_button = QPushButton("Izin Kaydet")
        self._consent_button.clicked.connect(self._record_consent)
        self._consent_button.setEnabled(self.ui.can(Perm.GUEST_EDIT))
        if not self._consent_button.isEnabled():
            self._consent_button.setToolTip(t("auth.no_permission"))
        actions.addWidget(self._consent_button)
        layout.addLayout(actions)

        # Genisleyen sutun KAYNAK'tir, izin turu degil. Izin turu kapali bir
        # kumedir ve en uzunu ("E-posta Pazarlama Izni") olculebilir; sabit
        # genislik verilince artan yer, uzunlugu onceden bilinemeyen serbest
        # metin alanina (kaynak) kalir. Tersi yapildiginda izin turu sutunu
        # bos yer israf ederken "check-in formu" degeri kirpiliyordu.
        self._consents_table = FilterableTableView(
            [
                Column("consent_type", "Izin Turu", width=145),
                Column("durum", "Durum", getter=self._consent_status, width=85),
                # Yalnizca gun gosterilir: tam zaman damgasi sutunu, izin turu
                # adinin kirpilmasina yol aciyordu. Saniye hassasiyetindeki iz
                # denetim gunlugunde zaten duruyor.
                Column("recorded_at", "Tarih", formatter=format_short_date, width=92),
                Column("source", "Kaynak", stretch=True),
            ],
            parent=self,
        )
        self._consents_table.setMinimumHeight(200)
        self._consents_stack = QStackedWidget()
        self._consents_stack.addWidget(self._consents_table)
        self._consents_stack.addWidget(
            EmptyState(
                "Bu misafir icin kayitli izin yok.",
                hint="Giris formunda alinan acik rizayi 'Izin Kaydet' ile isleyin.",
                icon="\U0001f4dd",
                parent=self,
            )
        )
        layout.addWidget(self._consents_stack, 1)
        return page

    # ----------------------------------------------------------------- #
    #  Veri
    # ----------------------------------------------------------------- #
    def load_data(self) -> None:
        with self.ui.service_context(commit=False) as ctx:
            summaries = GuestService(ctx).search(self._query, limit=self.LIST_LIMIT)

        self._table.set_rows(summaries)
        self._count_label.setText(f"{format_number(len(summaries))} kayit")
        if summaries:
            self._list_stack.setCurrentIndex(0)
        else:
            self._list_stack.setCurrentIndex(1 if self._query else 2)

        if not summaries:
            self._selected_guest_id = None
            self._profile_stack.setCurrentIndex(0)
            return

        # Onceki secim listede duruyorsa korunur; yoksa ilk satir secilir.
        # Satir sirasi TABLONUN siralamasindan alinir; kaynak listenin sirasi
        # kullanilsaydi siralama degistiginde yanlis misafir secilirdi.
        visible = self._table.visible_rows()
        target = self._selected_guest_id
        index = next(
            (position for position, row in enumerate(visible) if row.guest_id == target),
            0,
        )
        self._table.table.selectRow(index)

    def _apply_search(self) -> None:
        self._query = self._search.text().strip()
        self.refresh(force=True)

    def _on_selection_changed(self, row: object) -> None:
        if not isinstance(row, GuestSummary):
            return
        if row.guest_id == self._selected_guest_id and self._profile is not None:
            return
        self._selected_guest_id = row.guest_id
        self._load_profile(row.guest_id)

    def _load_profile(self, guest_id: int) -> None:
        try:
            with self.ui.service_context(commit=False) as ctx:
                profile = GuestService(ctx).get_profile(guest_id)
        except HotelError as exc:
            show_error(self, exc)
            return

        self._profile = profile
        self._render_profile(profile)
        self._profile_stack.setCurrentIndex(1)

    # ----------------------------------------------------------------- #
    #  Cizim
    # ----------------------------------------------------------------- #
    def _render_profile(self, profile: GuestProfile) -> None:
        summary = profile.summary

        self._profile_name.setText(summary.display_name or summary.full_name)

        self._vip_badge.setVisible(summary.is_vip)
        if summary.is_vip:
            self._vip_badge.set_status(f"VIP - {summary.vip_level}", "warning")

        self._blacklist_badge.setVisible(summary.is_blacklisted)
        # Kara listedeki kayit zaten kendi rozetini ve gerekce satirini
        # gosteriyor; ikinci bir uyari rozeti ayni bilgiyi tekrarlayip
        # basligi kalabaliklastirirdi.
        self._alert_badge.setVisible(summary.has_alert and not summary.is_blacklisted)
        self._blacklist_reason.setVisible(summary.is_blacklisted)
        if summary.is_blacklisted:
            self._blacklist_reason.setText(
                f"Kara listede. Gerekce: {summary.blacklist_reason or 'belirtilmemis'}"
            )
        self._blacklist_button.setText(
            "Kara Listeden Cikar" if summary.is_blacklisted else "Kara Listeye Al"
        )

        fields = self._general_fields
        fields["email"].setText(summary.email or "-")
        fields["phone"].setText(summary.phone or "-")
        fields["mobile"].setText(profile.mobile or "-")
        fields["birth_date"].setText(
            format_date(profile.birth_date)
            + (f" ({profile.age} yasinda)" if profile.age is not None else "")
        )
        fields["nationality"].setText(profile.nationality or "-")
        fields["language"].setText(guest_language_label(profile.preferred_language))
        fields["address"].setText(profile.address_line or "-")
        fields["city"].setText(
            " / ".join(part for part in (profile.city, profile.country) if part) or "-"
        )
        fields["vip"].setText(summary.vip_level)
        fields["company"].setText(profile.company_name or "-")
        fields["agency"].setText(profile.agency_name or "-")
        fields["stats"].setText(
            f"{summary.total_stays} konaklama - {profile.total_nights} gece - "
            f"{profile.total_revenue.format()}"
        )

        self._identity_type_label.setText(profile.identity_document_type)
        self._identity_value.setText(profile.identity_masked)
        self._reveal_button.setEnabled(
            self.ui.can(Perm.GUEST_VIEW_IDENTITY) and profile.has_identity
        )

        self._render_stays(profile.stays)
        self._render_notes(profile)
        self._render_consents(profile.consents)

    def _render_stays(self, stays: list[StayHistoryEntry]) -> None:
        self._stays_table.set_rows(stays)
        self._stays_stack.setCurrentIndex(0 if stays else 1)

    def _render_notes(self, profile: GuestProfile) -> None:
        while self._notes_body.count():
            item = self._notes_body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        # --- Tercihler ---
        preferences_card = Card("Tercihler", self)
        if profile.preferences:
            for preference in profile.preferences:
                line = QHBoxLayout()
                badge = StatusBadge(
                    "KRITIK" if preference.is_critical else preference.category,
                    "danger" if preference.is_critical else "info",
                )
                line.addWidget(badge)
                text = QLabel(
                    f"{preference.category}: {preference.value}"
                    if preference.is_critical
                    else preference.value
                )
                text.setWordWrap(True)
                line.addWidget(text, 1)
                preferences_card.add_layout(line)
        else:
            empty = QLabel("Kayitli tercih yok.")
            empty.setObjectName("Muted")
            preferences_card.add_widget(empty)
        self._notes_body.addWidget(preferences_card)

        # --- Notlar ---
        notes_card = Card("Personel Notlari", self)
        if profile.notes:
            for note in profile.notes:
                notes_card.add_widget(self._note_widget(note))
        else:
            empty = QLabel("Kayitli not yok.")
            empty.setObjectName("Muted")
            notes_card.add_widget(empty)
        self._notes_body.addWidget(notes_card)
        self._notes_body.addStretch(1)

    def _note_widget(self, note: NoteEntry) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        head = QHBoxLayout()
        if note.is_alert:
            head.addWidget(StatusBadge("UYARI", "danger"))
        author = QLabel(f"{note.author} - {format_datetime(note.created_at)}")
        author.setObjectName("Muted")
        head.addWidget(author)
        head.addStretch(1)
        layout.addLayout(head)

        content = QLabel(note.content)
        content.setWordWrap(True)
        if note.is_alert:
            # Uyari notu goz ile taranirken kaybolmamalidir; rozet tek basina
            # yeterli degil, metin de vurgulanir. Renk paletten alinir.
            content.setStyleSheet(f"color: {active_palette().danger}; font-weight: 600;")
        layout.addWidget(content)

        return holder

    def _render_consents(self, consents: list[ConsentEntry]) -> None:
        self._consents_table.set_rows(consents)
        self._consents_stack.setCurrentIndex(0 if consents else 1)

    # ----------------------------------------------------------------- #
    #  Eylemler
    # ----------------------------------------------------------------- #
    def _create_guest(self) -> None:
        dialog = GuestDialog(self.ui, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.result_summary is not None:
            self._selected_guest_id = dialog.result_summary.guest_id
            show_toast(self, "Misafir kaydi olusturuldu.", ToastLevel.SUCCESS)
        self._profile = None
        self.refresh(force=True)

    def _edit_guest(self) -> None:
        if self._selected_guest_id is None:
            return
        if not self.ui.can(Perm.GUEST_EDIT):
            return

        dialog = GuestDialog(self.ui, guest_id=self._selected_guest_id, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        show_toast(self, "Misafir kaydi guncellendi.", ToastLevel.SUCCESS)
        self._profile = None
        self.refresh(force=True)

    def _reveal_identity(self) -> None:
        """Kimlik numarasini acik gosterir ve denetime yazar."""
        if self._selected_guest_id is None:
            return

        if not confirm(
            self,
            "Kimlik numarasi acik olarak gosterilecek.",
            detail=(
                "Bu goruntuleme, kullanici adiniz ve zaman damgasiyla birlikte "
                "denetim gunlugune kaydedilir. Devam edilsin mi?"
            ),
            title="KVKK - Kimlik Goruntuleme",
        ):
            return

        try:
            # commit=True: denetim kaydinin kalici olmasi sarttir. Salt okuma
            # baglaminda cagrilsaydi kayit geri alinir ve iz kaybolurdu.
            with self.ui.service_context() as ctx:
                view = GuestService(ctx).reveal_identity(self._selected_guest_id)
        except HotelError as exc:
            show_error(self, exc)
            return

        self._identity_value.setText(view.value)
        if view.is_revealed:
            show_toast(
                self,
                "Kimlik goruntulemesi denetim gunlugune kaydedildi.",
                ToastLevel.WARNING,
            )
        else:
            show_toast(self, "Bu bilgiyi acik gorme yetkiniz yok.", ToastLevel.WARNING)

    def _toggle_blacklist(self) -> None:
        if self._selected_guest_id is None or self._profile is None:
            return

        summary = self._profile.summary
        removing = summary.is_blacklisted
        reason: str | None = None

        if removing:
            if not confirm(
                self,
                f"{summary.full_name} kara listeden cikarilsin mi?",
                detail="Islem denetim gunlugune kaydedilir.",
                dangerous=True,
            ):
                return
        else:
            dialog = _ReasonDialog(
                "Kara Listeye Al",
                f"{summary.full_name} kara listeye aliniyor.",
                self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            reason = dialog.reason
            if not confirm(
                self,
                f"{summary.full_name} kara listeye alinsin mi?",
                detail="Bu misafir icin yeni rezervasyonlarda uyari gosterilir.",
                dangerous=True,
            ):
                return

        try:
            with self.ui.service_context() as ctx:
                GuestService(ctx).set_blacklist(self._selected_guest_id, not removing, reason)
        except HotelError as exc:
            show_error(self, exc)
            return

        show_toast(
            self,
            "Kara liste kaydi guncellendi.",
            ToastLevel.SUCCESS if removing else ToastLevel.WARNING,
        )
        self._profile = None
        self.refresh(force=True)

    def _add_note(self) -> None:
        if self._selected_guest_id is None:
            return

        dialog = _NoteDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            with self.ui.service_context() as ctx:
                GuestService(ctx).add_note(
                    self._selected_guest_id,
                    dialog.content,
                    is_alert=dialog.is_alert,
                )
        except HotelError as exc:
            show_error(self, exc)
            return

        show_toast(self, "Not eklendi.", ToastLevel.SUCCESS)
        self._reload_profile()

    def _record_consent(self) -> None:
        if self._selected_guest_id is None:
            return

        dialog = _ConsentDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            with self.ui.service_context() as ctx:
                GuestService(ctx).record_consent(
                    self._selected_guest_id,
                    dialog.consent_type,
                    dialog.granted,
                    source=dialog.source,
                )
        except HotelError as exc:
            show_error(self, exc)
            return

        show_toast(
            self,
            "Izin kaydi olusturuldu." if dialog.granted else "Izin geri alma kaydi olusturuldu.",
            ToastLevel.SUCCESS,
        )
        self._reload_profile()

    def _reload_profile(self) -> None:
        if self._selected_guest_id is not None:
            self._load_profile(self._selected_guest_id)

    # ----------------------------------------------------------------- #
    #  Sutun yardimcilari
    # ----------------------------------------------------------------- #
    @staticmethod
    def _name_cell(row: GuestSummary) -> str:
        """Kara liste, renk disinda **metinle de** isaretlenir.

        Renk korlugu olan bir kullanici icin renk tek basina bilgi tasimaz;
        bu yuzden satirda acik bir etiket bulunur. Etiket adin **onune**
        yazilir: dar bir sutunda ad kirpilsa bile kritik bilgi gorunur kalir,
        sona yazilsaydi ilk kirpilan o olurdu.

        Yan etkisi bilincli: ada gore siralandiginda isaretli misafirler
        ("!" oneki) listenin basinda toplanir. Resepsiyon icin dogru davranis
        budur - sorunlu kaydin gozden kacmamasi gerekir.
        """
        if row.is_blacklisted:
            return f"! KARA LISTE - {row.full_name}"
        if row.has_alert:
            return f"! {row.full_name}"
        return row.full_name

    @staticmethod
    def _name_color(row: GuestSummary) -> str | None:
        palette = active_palette()
        if row.is_blacklisted:
            return palette.danger
        if row.has_alert:
            return palette.warning
        return None

    @staticmethod
    def _consent_status(row: ConsentEntry) -> str:
        if row.is_valid:
            return "Gecerli"
        return "Geri alindi" if row.revoked_at is not None else "Verilmedi"


# ==========================================================================
#  Kucuk yardimci diyaloglar
# ==========================================================================
class _ReasonDialog(QDialog):
    """Tek satirlik zorunlu gerekce soran diyalog."""

    def __init__(self, title: str, message: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        description = QLabel(message)
        description.setWordWrap(True)
        layout.addWidget(description)

        self._input = QLineEdit()
        self._input.setMaxLength(400)
        self._input.setPlaceholderText("Gerekce (zorunlu)")
        layout.addWidget(self._input)

        self._warning = QLabel("Gerekce zorunludur.")
        self._warning.setObjectName("BadgeWarning")
        self._warning.setVisible(False)
        layout.addWidget(self._warning)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(t("common.cancel"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        accept = QPushButton(t("common.ok"))
        accept.setObjectName("Primary")
        accept.setDefault(True)
        accept.clicked.connect(self._accept)
        buttons.addWidget(accept)
        layout.addLayout(buttons)

    def _accept(self) -> None:
        if not self._input.text().strip():
            self._warning.setVisible(True)
            return
        self.accept()

    @property
    def reason(self) -> str:
        return self._input.text().strip()


class _NoteDialog(QDialog):
    """Misafir notu ekleme."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Not Ekle")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        self._editor = QPlainTextEdit()
        self._editor.setPlaceholderText("Not icerigi")
        self._editor.setMinimumHeight(140)
        layout.addWidget(self._editor)

        self._alert = QCheckBox("Uyari notu (rezervasyon ve giris ekranlarinda vurgulanir)")
        layout.addWidget(self._alert)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(t("common.cancel"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = QPushButton(t("common.save"))
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(self._accept)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _accept(self) -> None:
        if self._editor.toPlainText().strip():
            self.accept()

    @property
    def content(self) -> str:
        return self._editor.toPlainText().strip()

    @property
    def is_alert(self) -> bool:
        return self._alert.isChecked()


class _ConsentDialog(QDialog):
    """KVKK izni verme / geri alma kaydi."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("KVKK Izin Kaydi")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)

        self._type = QComboBox()
        for value, label in ConsentType.choices():
            self._type.addItem(label, value)
        form.addRow("Izin Turu", self._type)

        self._action = QComboBox()
        self._action.addItem("Izin verildi", True)
        self._action.addItem("Izin geri alindi", False)
        form.addRow("Islem", self._action)

        self._source = QLineEdit()
        self._source.setMaxLength(100)
        self._source.setPlaceholderText("Or. giris formu, web sitesi, telefon")
        form.addRow("Kaynak", self._source)

        layout.addLayout(form)

        note = QLabel(
            "Bu kayit silinemez ve degistirilemez; izin gecmisi KVKK denetiminde "
            "ispat niteligindedir."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(t("common.cancel"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = QPushButton(t("common.save"))
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    @property
    def consent_type(self) -> ConsentType:
        return ConsentType(self._type.currentData())

    @property
    def granted(self) -> bool:
        return bool(self._action.currentData())

    @property
    def source(self) -> str | None:
        return self._source.text().strip() or None


__all__ = ["GuestsPage"]
