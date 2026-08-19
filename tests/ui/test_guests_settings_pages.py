"""Misafirler ve Ayarlar ekranlarinin arayuz testleri.

Testler gercek Qt bilesenleri ve bellek ici bir veritabani kullanir.
Yalnizca iki sey taklit edilir:

* :func:`app.ui.session.session_scope` - arayuz oturumu uygulama
  veritabanina degil, testin gecici oturumuna baglanir.
* Modal kutular (``confirm``) - aksi halde test kullanici girdisi bekleyerek
  kilitlenirdi.

``QT_QPA_PLATFORM=offscreen`` kok ``conftest.py`` icinde ayarlidir.
"""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal

import pytest
from PySide6.QtWidgets import QLineEdit, QTabWidget
from sqlalchemy import select

from app.application.context import ServiceContext
from app.application.services.guest_service import GuestService
from app.domain.enums import AuditAction, ConsentType, VIPLevel
from app.infrastructure.db.models import Permission, Role, User
from app.infrastructure.db.models.billing import TaxRate
from app.infrastructure.db.models.security import AuditLog
from app.security.passwords import hash_password
from app.security.permissions import Perm
from app.ui.dialogs import guest_dialog as guest_dialog_module
from app.ui.dialogs.guest_dialog import GuestDialog
from app.ui.pages import guests_page as guests_module
from app.ui.pages import settings_page as settings_module
from app.ui.pages.guests_page import GuestsPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.session import UiSession
from app.ui.theme import ThemeMode, active_palette, apply_theme

pytestmark = pytest.mark.ui


# --------------------------------------------------------------------------
#  Fiksturler
# --------------------------------------------------------------------------
@pytest.fixture
def patched_scope(secured_session, monkeypatch):
    """Arayuz oturumunu test veritabanina baglar."""

    @contextmanager
    def fake_scope(*, commit: bool = True):
        yield secured_session

    monkeypatch.setattr("app.ui.session.session_scope", fake_scope)
    return secured_session


@pytest.fixture
def ui_session(patched_scope, admin_user, sample_property) -> UiSession:
    """Tum yetkilere sahip arayuz oturumu."""
    session = UiSession(user=admin_user, token="test-token")
    session.set_property(sample_property.id, sample_property.name)
    return session


@pytest.fixture
def frontdesk_ui_session(patched_scope, sample_property) -> UiSession:
    """Misafiri gorebilen ama kimligi ACIK goremeyen kullanici."""
    role = patched_scope.scalars(select(Role).where(Role.code == "frontdesk")).one()
    user = User(
        username="resepsiyon_ui",
        full_name="Test Resepsiyonist",
        password_hash=hash_password("ResepsiyonUi2026!"),
        is_superuser=False,
    )
    user.roles.append(role)
    patched_scope.add(user)
    patched_scope.commit()

    session = UiSession(user=user, token="frontdesk-token")
    session.set_property(sample_property.id, sample_property.name)
    return session


@pytest.fixture
def settings_viewer_session(patched_scope, sample_property) -> UiSession:
    """Ayarlari gorebilen ama degistiremeyen kullanici."""
    codes = [Perm.SETTINGS_VIEW, Perm.PROPERTY_VIEW, Perm.RATE_VIEW]
    permissions = list(
        patched_scope.scalars(select(Permission).where(Permission.code.in_(codes))).all()
    )
    role = Role(code="ayar_izleyici", name="Ayar Izleyici", is_system=False)
    role.permissions.extend(permissions)
    patched_scope.add(role)

    user = User(
        username="ayar_izleyici",
        full_name="Ayar Izleyici",
        password_hash=hash_password("AyarIzleyici2026!"),
        is_superuser=False,
    )
    user.roles.append(role)
    patched_scope.add(user)
    patched_scope.commit()

    session = UiSession(user=user, token="viewer-token")
    session.set_property(sample_property.id, sample_property.name)
    return session


@pytest.fixture
def seeded_guests(patched_scope, admin_user, sample_property):
    """Uc misafir: VIP + kimlikli, kara listeli ve sade kayit."""
    ctx = ServiceContext(session=patched_scope, user=admin_user, property_id=sample_property.id)
    service = GuestService(ctx)

    vip = service.create(
        first_name="Deniz",
        last_name="Yildizli",
        email="deniz.yildizli@ornek-test.local",
        phone="+90 555 000 00 01",
        identity_number="11111111110",
        vip_level=VIPLevel.GOLD,
    )
    banned = service.create(
        first_name="Kerem",
        last_name="Aksoy",
        phone="+90 555 000 00 02",
    )
    plain = service.create(first_name="Selin", last_name="Bozkurt")

    service.set_blacklist(banned.guest_id, True, reason="Odeme yapmadan ayrildi")
    service.record_consent(vip.guest_id, ConsentType.MARKETING_EMAIL, True, source="giris formu")
    service.add_note(vip.guest_id, "Sessiz oda tercih ediyor.", is_alert=True)

    patched_scope.commit()
    return {"vip": vip, "banned": banned, "plain": plain}


@pytest.fixture
def guests_page(qtbot, ui_session, seeded_guests) -> GuestsPage:
    """Verisi yuklenmis misafir ekrani."""
    screen = GuestsPage(ui_session)
    qtbot.addWidget(screen)
    screen.on_shown()
    return screen


@pytest.fixture
def tax_rate(patched_scope, sample_property) -> TaxRate:
    """Ornek KDV orani."""
    rate = TaxRate(
        property_id=sample_property.id,
        code="KDV10",
        name="Konaklama KDV",
        rate_percent=Decimal("10.00"),
        is_included_in_price=True,
        is_default=True,
    )
    patched_scope.add(rate)
    patched_scope.commit()
    return rate


@pytest.fixture
def restore_theme(qtbot):
    """Tema testleri uygulamanin genel stilini degistirir; sonra geri alinir."""
    from PySide6.QtWidgets import QApplication

    previous = active_palette().name
    yield
    app = QApplication.instance()
    if app is not None:
        apply_theme(app, ThemeMode(previous))


@pytest.fixture
def settings_page(qtbot, ui_session, tax_rate, monkeypatch) -> SettingsPage:
    """Verisi yuklenmis ayarlar ekrani (yedek listesi bos)."""
    monkeypatch.setattr(settings_module, "list_backups", lambda: [])
    screen = SettingsPage(ui_session)
    qtbot.addWidget(screen)
    screen.on_shown()
    return screen


def find_guest_row(screen: GuestsPage, guest_id: int):
    for row in screen._table.model.rows:
        if row.guest_id == guest_id:
            return row
    raise AssertionError(f"{guest_id} kimlikli misafir tabloda yok.")


# --------------------------------------------------------------------------
#  Misafirler ekrani
# --------------------------------------------------------------------------
class TestMisafirlerEkrani:
    def test_ekran_olusur_ve_liste_yuklenir(self, guests_page, seeded_guests):
        assert guests_page._table.total_count == 3
        assert guests_page._list_stack.currentIndex() == 0
        assert "3 kayit" in guests_page._count_label.text()

    def test_kara_listedeki_misafir_metinle_isaretlenir(self, guests_page, seeded_guests):
        row = find_guest_row(guests_page, seeded_guests["banned"].guest_id)
        assert row.is_blacklisted is True
        # Isaret adin ONUNDE olmalidir: sutun dar oldugunda ad kirpilir ama
        # kritik bilgi gorunur kalir.
        assert GuestsPage._name_cell(row).startswith("! KARA LISTE - ")
        assert GuestsPage._name_color(row) == active_palette().danger

    def test_secim_profili_yukler(self, guests_page, seeded_guests):
        row = find_guest_row(guests_page, seeded_guests["vip"].guest_id)
        guests_page._on_selection_changed(row)

        assert guests_page._profile_stack.currentIndex() == 1
        assert "Deniz Yildizli" in guests_page._profile_name.text()
        assert guests_page._general_fields["email"].text() == ("deniz.yildizli@ornek-test.local")
        assert guests_page._general_fields["vip"].text() == "Altin"

    def test_kimlik_numarasi_maskeli_gorunur(self, guests_page, seeded_guests):
        guests_page._on_selection_changed(
            find_guest_row(guests_page, seeded_guests["vip"].guest_id)
        )

        assert guests_page._identity_value.text() == "111*****110"
        assert "11111111110" != guests_page._identity_value.text()

    def test_goster_dugmesi_yetkisiz_kullanicida_pasif(
        self, qtbot, frontdesk_ui_session, seeded_guests
    ):
        screen = GuestsPage(frontdesk_ui_session)
        qtbot.addWidget(screen)
        screen.on_shown()

        assert not screen._reveal_button.isEnabled()
        assert "ayri yetki" in screen._reveal_button.toolTip()

    def test_goster_dugmesi_acik_deger_ve_denetim_kaydi_uretir(
        self, guests_page, seeded_guests, patched_scope, monkeypatch
    ):
        monkeypatch.setattr(guests_module, "confirm", lambda *a, **k: True)
        guests_page._on_selection_changed(
            find_guest_row(guests_page, seeded_guests["vip"].guest_id)
        )

        guests_page._reveal_identity()

        assert guests_page._identity_value.text() == "11111111110"
        entries = list(
            patched_scope.scalars(
                select(AuditLog).where(
                    AuditLog.action == AuditAction.READ,
                    AuditLog.entity_type == "Guest",
                )
            )
        )
        assert len(entries) == 1
        assert "11111111110" not in entries[0].description

    def test_goster_onaylanmazsa_deger_degismez(
        self, guests_page, seeded_guests, patched_scope, monkeypatch
    ):
        monkeypatch.setattr(guests_module, "confirm", lambda *a, **k: False)
        guests_page._on_selection_changed(
            find_guest_row(guests_page, seeded_guests["vip"].guest_id)
        )

        guests_page._reveal_identity()

        assert guests_page._identity_value.text() == "111*****110"
        assert (
            patched_scope.scalars(
                select(AuditLog).where(AuditLog.action == AuditAction.READ)
            ).first()
            is None
        )

    def test_konaklama_ve_kvkk_sekmeleri_dolar(self, guests_page, seeded_guests):
        guests_page._on_selection_changed(
            find_guest_row(guests_page, seeded_guests["vip"].guest_id)
        )

        # Hic konaklama yok -> bos durum gosterilir, bos tablo birakilmaz.
        assert guests_page._stays_stack.currentIndex() == 1
        # Bir izin kaydi var -> tablo gosterilir.
        assert guests_page._consents_stack.currentIndex() == 0
        assert guests_page._consents_table.total_count == 1

    def test_uyari_notu_profilde_gorunur(self, guests_page, seeded_guests):
        guests_page._on_selection_changed(
            find_guest_row(guests_page, seeded_guests["vip"].guest_id)
        )

        assert guests_page._profile is not None
        assert guests_page._profile.notes[0].is_alert is True

    def test_sonucsuz_aramada_bos_durum_gosterilir(self, guests_page):
        guests_page._search.setText("boyle-bir-misafir-yok")
        guests_page._apply_search()

        assert guests_page._table.total_count == 0
        assert guests_page._list_stack.currentIndex() == 1
        assert guests_page._profile_stack.currentIndex() == 0

    def test_hic_kayit_yoksa_farkli_bos_durum_gosterilir(self, qtbot, ui_session):
        """'Kayit yok' ile 'arama sonucsuz' ayni sey degildir."""
        screen = GuestsPage(ui_session)
        qtbot.addWidget(screen)
        screen.on_shown()

        assert screen._table.total_count == 0
        assert screen._list_stack.currentIndex() == 2

    def test_telefon_ile_arama_calisir(self, guests_page, seeded_guests):
        guests_page._search.setText("5550000002")
        guests_page._apply_search()

        assert guests_page._table.total_count == 1
        assert guests_page._table.model.rows[0].guest_id == seeded_guests["banned"].guest_id

    def test_yetkisiz_kullanicida_kara_liste_dugmesi_pasif(
        self, qtbot, frontdesk_ui_session, seeded_guests
    ):
        screen = GuestsPage(frontdesk_ui_session)
        qtbot.addWidget(screen)
        screen.on_shown()

        assert not screen._blacklist_button.isEnabled()
        assert screen._new_button.isEnabled()  # frontdesk misafir olusturabilir


# --------------------------------------------------------------------------
#  Misafir diyalogu
# --------------------------------------------------------------------------
class TestMisafirDiyalogu:
    def test_yeni_misafir_kaydedilir(self, qtbot, ui_session, patched_scope, monkeypatch):
        monkeypatch.setattr("app.ui.widgets.common.confirm", lambda *a, **k: True)
        dialog = GuestDialog(ui_session)
        qtbot.addWidget(dialog)

        dialog._first_name.setText("Yaren")
        dialog._last_name.setText("Kilicaslan")
        dialog._phone.setText("+90 555 000 00 09")
        dialog._identity_number.setText("33333333330")
        dialog._save()

        assert dialog.result_summary is not None
        assert dialog.result_summary.full_name == "Yaren Kilicaslan"

    def test_mukerrer_kayit_uyarisi_gosterilir(self, qtbot, ui_session, seeded_guests):
        dialog = GuestDialog(ui_session)
        qtbot.addWidget(dialog)

        dialog._first_name.setText("Deniz")
        dialog._last_name.setText("Yildizli")
        matches = dialog._check_duplicates()

        assert matches, "Ayni isimli kayit bulunamadi."
        assert not dialog._duplicate_label.isHidden()
        assert "Benzer kayit bulundu" in dialog._duplicate_label.text()

    def test_duzenleme_kipinde_kimlik_alani_bos_gelir(self, qtbot, ui_session, seeded_guests):
        """Kayitli numara forma yazilmaz; yalnizca maskeli ipucu gosterilir."""
        dialog = GuestDialog(ui_session, guest_id=seeded_guests["vip"].guest_id)
        qtbot.addWidget(dialog)

        assert dialog._identity_number.text() == ""
        assert "111*****110" in dialog._identity_number.placeholderText()
        assert dialog._first_name.text() == "Deniz"


# --------------------------------------------------------------------------
#  Ayarlar ekrani
# --------------------------------------------------------------------------
class TestAyarlarEkrani:
    def test_ekran_olusur_ve_tesis_bilgisi_yuklenir(self, settings_page, sample_property):
        assert settings_page._property_info is not None
        assert settings_page._property_fields["name"].text() == sample_property.name
        assert "TEST01" in settings_page._property_summary.text()

    def test_vergi_orani_listelenir(self, settings_page, tax_rate):
        assert settings_page._tax_stack.currentIndex() == 0
        assert settings_page._tax_table.total_count == 1
        assert settings_page._tax_table.model.rows[0].code == "KDV10"

    def test_tema_degisimi_aninda_uygulanir(self, settings_page, restore_theme):
        index = settings_page._theme_combo.findData(ThemeMode.LIGHT.value)
        settings_page._theme_combo.setCurrentIndex(index)
        assert active_palette().name == "light"

        index = settings_page._theme_combo.findData(ThemeMode.DARK.value)
        settings_page._theme_combo.setCurrentIndex(index)
        assert active_palette().name == "dark"

    def test_dil_degisimi_yeniden_baslatma_uyarisi_verir(self, settings_page):
        from app.ui.i18n import get_language, set_language

        previous = get_language()
        try:
            index = settings_page._language_combo.findData("en")
            settings_page._language_combo.setCurrentIndex(index)
            assert "yeniden baslatin" in settings_page._language_note.text()
        finally:
            set_language(previous)

    def test_api_anahtari_alani_parola_kipinde(self, settings_page):
        assert settings_page._api_key_input.echoMode() == QLineEdit.EchoMode.Password
        # Kayitli anahtar yalnizca maskeli ozet olarak gorunur.
        assert (
            "..." in settings_page._current_key_label.text()
            or settings_page._current_key_label.text()
            in {
                "(tanimsiz)",
                "(bos)",
                "********",
            }
        )

    def test_saglayici_listesi_dolu_ve_durum_denenmemis(self, settings_page):
        rows = settings_page._provider_table.model.rows
        assert len(rows) == 4
        assert {row.provider for row in rows} == {
            "lmstudio",
            "nvidia",
            "openai",
            "anthropic",
        }
        assert all(row.status == "Denenmedi" for row in rows)

    def test_yapay_zeka_kapaliyken_test_dugmesi_pasif(self, settings_page):
        """Testlerde HOTEL_AI_ENABLED=false; calismayacak bir islem vaat edilmez."""
        assert not settings_page._test_button.isEnabled()
        assert "kapali" in settings_page._health_label.text()

    def test_yedek_yoksa_bos_durum_gosterilir(self, settings_page):
        assert settings_page._backup_stack.currentIndex() == 1

    def test_yedek_listesi_dosyalari_gosterir(self, qtbot, ui_session, tmp_path, monkeypatch):
        backup = tmp_path / "hotel_20260815_120000.db"
        backup.write_bytes(b"0" * 2048)
        monkeypatch.setattr(settings_module, "list_backups", lambda: [backup])

        screen = SettingsPage(ui_session)
        qtbot.addWidget(screen)
        screen.on_shown()

        assert screen._backup_stack.currentIndex() == 0
        assert screen._backup_table.total_count == 1
        assert screen._backup_table.model.rows[0].file_name == backup.name

    def test_yetkisiz_kullanicida_vergi_dugmeleri_pasif(
        self, qtbot, settings_viewer_session, tax_rate, monkeypatch
    ):
        monkeypatch.setattr(settings_module, "list_backups", lambda: [])
        screen = SettingsPage(settings_viewer_session)
        qtbot.addWidget(screen)
        screen.on_shown()

        assert not screen._tax_add_button.isEnabled()
        assert not screen._tax_edit_button.isEnabled()
        assert not screen._create_backup_button.isEnabled()
        assert not screen._restore_button.isEnabled()
        # Tesis alanlari salt okunur olmalidir.
        assert screen._property_fields["name"].isReadOnly()

    def test_vergi_diyalogu_orani_decimal_uretir(self, qtbot, tax_rate):
        """Para/oran degerleri float olarak tasinmaz."""
        row = settings_module._TaxRow(
            tax_id=tax_rate.id,
            code="KDV10",
            name="Konaklama KDV",
            rate_percent=Decimal("10.00"),
            is_included_in_price=True,
            is_default=True,
            is_active=True,
        )
        dialog = settings_module._TaxRateDialog(row)
        qtbot.addWidget(dialog)

        values = dialog.values
        assert isinstance(values["rate_percent"], Decimal)
        assert values["rate_percent"] == Decimal("10.00")
        assert values["code"] == "KDV10"

    def test_geri_yukleme_onay_metni_tanimli(self):
        """Yikici islem, refleksle onaylanamayacak bir metin ister."""
        assert settings_module.RESTORE_PHRASE == "GERI YUKLE"

    def test_geri_yukleme_dugmesi_dogru_metin_yazilmadan_pasif(self, qtbot):
        dialog = settings_module._PhraseDialog(settings_module.RESTORE_PHRASE)
        qtbot.addWidget(dialog)

        assert not dialog._confirm_button.isEnabled()
        dialog._input.setText("geri yukle")
        assert not dialog._confirm_button.isEnabled()
        dialog._input.setText(settings_module.RESTORE_PHRASE)
        assert dialog._confirm_button.isEnabled()


# --------------------------------------------------------------------------
#  Bagimsiz gozden gecirmede bulunan kusurlarin gerilemesi
# --------------------------------------------------------------------------
class TestGozdenGecirmeDuzeltmeleri:
    """Render incelemesinde ortaya cikan hatalarin tekrarlamasini onler."""

    def test_dil_katalogu_arayuz_dilleriyle_ayni_degil(self):
        """Misafirin dili, arayuzun konustugu dillerle sinirli olamaz.

        ``SUPPORTED_LANGUAGES`` yalnizca ``tr``/``en`` icerir. Diyalog onu
        kullandiginda Almanca ve Rusca konusan misafirler temsil edilemiyordu.
        """
        assert set(guest_dialog_module.GUEST_LANGUAGES) >= {"tr", "en", "de", "ru"}
        # Turkce formda "English" yazmaz.
        assert guest_dialog_module.GUEST_LANGUAGES["en"] == "Ingilizce"

    def test_profil_ve_form_ayni_dil_adini_kullanir(self, guests_page, seeded_guests):
        """Iki ayri katalog tutuldugunda profil 'Ingilizce', form 'English' diyordu."""
        guests_page._on_selection_changed(
            find_guest_row(guests_page, seeded_guests["vip"].guest_id)
        )
        assert guests_page._general_fields["language"].text() == "Turkce"
        assert guest_dialog_module.guest_language_label("en") == "Ingilizce"
        assert guest_dialog_module.guest_language_label("de") == "Almanca"
        # Taninmayan kod kaybolmaz, buyuk harfle gosterilir.
        assert guest_dialog_module.guest_language_label("pt") == "PT"

    def test_katalog_disi_dil_kaydederken_degismez(
        self, qtbot, ui_session, patched_scope, seeded_guests
    ):
        """Asil kusur: 'ru' konusan misafir kaydedilince sessizce 'tr' oluyordu."""
        guest_id = seeded_guests["plain"].guest_id
        ctx = ServiceContext(
            session=patched_scope,
            user=ui_session.user,
            property_id=ui_session.property_id,
        )
        GuestService(ctx).update(guest_id, preferred_language="ru")
        patched_scope.commit()

        dialog = GuestDialog(ui_session, guest_id=guest_id)
        qtbot.addWidget(dialog)

        assert dialog._language.currentData() == "ru"
        assert dialog._form_values()["preferred_language"] == "ru"

        dialog._save()
        patched_scope.commit()

        assert GuestService(ctx).get_profile(guest_id).preferred_language == "ru"

    def test_hicbir_katalogda_olmayan_dil_de_korunur(
        self, qtbot, ui_session, patched_scope, seeded_guests
    ):
        """Katalogda hic bulunmayan bir kod bile secenek olarak eklenir."""
        guest_id = seeded_guests["plain"].guest_id
        ctx = ServiceContext(
            session=patched_scope,
            user=ui_session.user,
            property_id=ui_session.property_id,
        )
        GuestService(ctx).update(guest_id, preferred_language="pt")
        patched_scope.commit()

        dialog = GuestDialog(ui_session, guest_id=guest_id)
        qtbot.addWidget(dialog)

        assert dialog._language.currentData() == "pt"

    def test_uzun_deger_alanin_basindan_gosterilir(self, qtbot, ui_session, seeded_guests):
        """``setText`` imleci sona birakir; e-posta bastan kirpilmis gorunurdu."""
        dialog = GuestDialog(ui_session, guest_id=seeded_guests["vip"].guest_id)
        qtbot.addWidget(dialog)

        assert dialog._email.text() == "deniz.yildizli@ornek-test.local"
        assert dialog._email.cursorPosition() == 0
        assert dialog._address.cursorPosition() == 0

    def test_uyari_notu_profil_basliginda_rozetle_gorunur(self, guests_page, seeded_guests):
        """Listede '!' ile isaretlenen kaydin profilinde de karsiligi olmalidir."""
        guests_page._on_selection_changed(
            find_guest_row(guests_page, seeded_guests["vip"].guest_id)
        )
        assert not guests_page._alert_badge.isHidden()

        # Kara listedeki kayit kendi rozetini gosterir; ikinci uyari tekrar olurdu.
        guests_page._on_selection_changed(
            find_guest_row(guests_page, seeded_guests["banned"].guest_id)
        )
        assert guests_page._alert_badge.isHidden()
        assert not guests_page._blacklist_badge.isHidden()

    def test_kvkk_tablosunda_genisleyen_sutun_kaynaktir(self, guests_page):
        """Izin turu kapali bir kumedir; artan yer serbest metne kalmalidir."""
        columns = {column.key: column for column in guests_page._consents_table.model.columns}
        assert columns["source"].stretch is True
        assert columns["consent_type"].stretch is False
        assert columns["consent_type"].width == 145

    def test_misafir_listesi_sutun_genislikleri_daraltilmadi(self, guests_page):
        """Daraltma denendi ve telefon/VIP/baslik kirpildi; degerler sabittir."""
        columns = {column.key: column for column in guests_page._table.model.columns}
        assert columns["phone"].width == 132
        assert columns["vip_level"].width == 76
        assert columns["total_stays"].width == 84
        assert columns["email"].stretch is True

    def test_tablo_sekmelerinde_genislik_siniri_yok(self, settings_page):
        """Sinir formlar icindir; tablo sekmesinde sagda bos sutun birakiyordu."""
        tabs = settings_page.findChild(QTabWidget)
        limits = [tabs.widget(index).widget().maximumWidth() for index in range(tabs.count())]
        form_limit = settings_module._FORM_MAX_WIDTH

        assert limits[0] == form_limit  # Genel - form
        assert limits[2] == form_limit  # Yapay Zeka - form
        assert limits[1] > form_limit  # Vergi - tablo
        assert limits[3] > form_limit  # Yedekleme - tablo

    def test_sayi_alanlarina_ok_dugmesi_duzeltmesi_uygulandi(self, settings_page):
        """Oklar cercevenin disinda yan yana ciziliyordu."""
        for spin in (
            settings_page._timeout,
            settings_page._temperature,
            settings_page._max_tokens,
        ):
            assert "subcontrol-position: top right" in spin.styleSheet()

    def test_tesis_alanlari_bastan_gosterilir(self, settings_page):
        for field in settings_page._property_fields.values():
            assert field.cursorPosition() == 0
