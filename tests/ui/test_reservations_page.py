"""Rezervasyon ekrani ve yeni rezervasyon diyalogu testleri.

Testler gercek bir veritabani (bellek ici SQLite) ve gercek Qt bilesenleri
kullanir; yalnizca iki sey taklit edilir:

* :func:`app.ui.session.session_scope` - arayuz oturumu uygulama
  veritabanina degil, testin gecici oturumuna baglanir.
* Modal kutular (``show_error``, ``confirm``, ucret bildirimi) - aksi halde
  test kullanici girdisi bekleyerek kilitlenirdi.

``QT_QPA_PLATFORM=offscreen`` kok ``conftest.py`` icinde ayarlidir.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QLabel
from sqlalchemy import select

from app.application.context import ServiceContext
from app.application.services.reservation_service import ReservationService, RoomRequest
from app.core.exceptions import OverlappingReservationError
from app.domain.enums import ReservationStatus
from app.domain.rules.reservation_state import available_actions
from app.infrastructure.db.base import utcnow
from app.infrastructure.db.models import Role, User
from app.infrastructure.db.models.guests import Guest
from app.infrastructure.db.models.reservations import Reservation
from app.security.passwords import hash_password
from app.ui.dialogs import reservation_dialog as dialog_module
from app.ui.dialogs.reservation_dialog import AvailabilityOption, ReservationDialog, parse_amount
from app.ui.pages import reservations_page as page_module
from app.ui.pages.reservations_page import ReservationRow, ReservationsPage
from app.ui.session import UiSession

pytestmark = pytest.mark.ui


# --------------------------------------------------------------------------
#  Fiksturler
# --------------------------------------------------------------------------
@pytest.fixture
def patched_scope(secured_session, monkeypatch):
    """Arayuz oturumunu test veritabanina baglar.

    ``UiSession.service_context`` her cagrida yeni bir oturum acar; testte
    tek bir oturum kullanmak, servisin yazdigini testin dogrudan
    gorebilmesini saglar.
    """

    @contextmanager
    def fake_scope(*, commit: bool = True):
        yield secured_session

    monkeypatch.setattr("app.ui.session.session_scope", fake_scope)
    return secured_session


@pytest.fixture
def ui_session(
    patched_scope,
    admin_user,
    sample_property,
    sample_room_type,
    sample_rooms,
    sample_rate_plan,
) -> UiSession:
    """Tum yetkilere sahip arayuz oturumu (oda ve tarife hazir)."""
    session = UiSession(user=admin_user, token="test-token")
    session.set_property(sample_property.id, sample_property.name)
    return session


@pytest.fixture
def viewer_ui_session(patched_scope, sample_property, sample_rooms) -> UiSession:
    """Yalnizca goruntuleme yetkisi olan kullanicinin oturumu."""
    role = patched_scope.scalars(select(Role).where(Role.code == "viewer")).one()
    user = User(
        username="izleyici",
        full_name="Test Izleyici",
        password_hash=hash_password("IzleyiciTest2026!"),
        is_superuser=False,
    )
    user.roles.append(role)
    patched_scope.add(user)
    patched_scope.commit()

    session = UiSession(user=user, token="viewer-token")
    session.set_property(sample_property.id, sample_property.name)
    return session


@pytest.fixture
def seeded(
    patched_scope, admin_user, sample_property, sample_room_type, sample_rooms, sample_guest
):
    """Dort rezervasyon: onayli, opsiyonlu, iptal ve gecmis tarihli."""
    ctx = ServiceContext(session=patched_scope, user=admin_user, property_id=sample_property.id)
    service = ReservationService(ctx)

    second = Guest(first_name="Kerem", last_name="Aksoy", phone="+90 5XX XXX XX 02")
    third = Guest(first_name="Selin", last_name="Bozkurt", phone="+90 5XX XXX XX 03")
    patched_scope.add_all([second, third])
    patched_scope.flush()

    start = utcnow().date() + timedelta(days=7)
    past = utcnow().date() - timedelta(days=5)

    def make(room, guest_id, first_day, status=ReservationStatus.CONFIRMED):
        return service.create_reservation(
            guest_id=guest_id,
            room_requests=[
                RoomRequest(
                    room_type_id=sample_room_type.id,
                    room_id=room.id,
                    check_in=first_day,
                    check_out=first_day + timedelta(days=2),
                )
            ],
            status=status,
        )

    confirmed = make(sample_rooms[0], sample_guest.id, start)
    tentative = make(sample_rooms[1], second.id, start, ReservationStatus.TENTATIVE)
    cancelled = make(sample_rooms[2], third.id, start)
    service.cancel(cancelled.id, reason="Misafir vazgecti")
    old = make(sample_rooms[0], sample_guest.id, past)

    patched_scope.commit()
    return {
        "confirmed": confirmed,
        "tentative": tentative,
        "cancelled": cancelled,
        "past": old,
    }


@pytest.fixture
def page(qtbot, ui_session, seeded) -> ReservationsPage:
    """Verisi yuklenmis rezervasyon ekrani."""
    screen = ReservationsPage(ui_session)
    qtbot.addWidget(screen)
    screen.on_shown()
    return screen


@pytest.fixture
def dialog(qtbot, ui_session) -> ReservationDialog:
    """Yeni rezervasyon diyalogu."""
    window = ReservationDialog(ui_session)
    qtbot.addWidget(window)
    return window


def find_row(screen: ReservationsPage, number: str) -> ReservationRow:
    """Onay numarasindan tablo satirini bulur."""
    for row in screen._table.model.rows:
        if row.confirmation_number == number:
            return row
    raise AssertionError(f"{number} numarali satir tabloda yok.")


def set_dates(window: ReservationDialog, first_day, last_day) -> None:
    window._check_in.setDate(QDate(first_day.year, first_day.month, first_day.day))
    window._check_out.setDate(QDate(last_day.year, last_day.month, last_day.day))


def price_lines(window: ReservationDialog) -> list[str]:
    """Fiyat dokumu panelindeki tum etiket metinlerini toplar."""
    texts: list[str] = []
    for index in range(window._price_layout.count()):
        widget = window._price_layout.itemAt(index).widget()
        if widget is None:
            continue
        if isinstance(widget, QLabel):
            texts.append(widget.text())
        texts.extend(child.text() for child in widget.findChildren(QLabel))
    return texts


def select_first_available(window: ReservationDialog) -> AvailabilityOption:
    """Musaitlik tablosundaki ilk secilebilir satiri secer."""
    for position, option in enumerate(window._availability_table.visible_rows()):
        if option.is_selectable:
            window._availability_table.table.selectRow(position)
            return option
    raise AssertionError("Secilebilir oda tipi bulunamadi.")


# --------------------------------------------------------------------------
#  Ekran: yukleme ve suzgecler
# --------------------------------------------------------------------------
class TestListeleme:
    def test_sayfa_olusur_ve_veri_yuklenir(self, page, seeded):
        assert page._table.total_count == 4
        assert page._stack.currentIndex() == 0
        numbers = {row.confirmation_number for row in page._table.model.rows}
        assert seeded["confirmed"].confirmation_number in numbers

    def test_satirlar_misafir_oda_ve_tutar_tasir(self, page, seeded):
        row = find_row(page, seeded["confirmed"].confirmation_number)
        assert row.guest_name == "Deniz Yildizli"
        assert row.rooms_text == "101"
        assert row.nights == 2
        # 2 gece x 1000 TL taban fiyat
        assert row.total.amount == Decimal("2000.00")
        assert row.balance.amount == Decimal("2000.00")

    def test_ozet_satiri_gosterilen_ve_toplam_sayiyi_yazar(self, page):
        text = page._summary_label.text()
        assert "4 rezervasyon gosteriliyor" in text
        assert "toplam 4" in text

    def test_arama_suzgeci_satir_sayisini_azaltir(self, page, seeded):
        page.set_search_query(seeded["tentative"].confirmation_number)
        assert page._table.visible_count == 1
        assert page._table.total_count == 4
        assert page._table.visible_rows()[0].guest_name == "Kerem Aksoy"

    def test_arama_misafir_adinda_da_calisir(self, page):
        page.set_search_query("Selin")
        assert page._table.visible_count == 1

    def test_arama_kutusu_gecikmeli_sinyal_yayar(self, qtbot, page, seeded):
        page._search.setText(seeded["tentative"].confirmation_number)
        qtbot.wait(450)  # SearchBox 300 ms bekletir
        assert page._table.visible_count == 1

    def test_durum_suzgeci_calisir(self, page):
        index = page._status_combo.findData(ReservationStatus.CANCELLED.value)
        page._status_combo.setCurrentIndex(index)
        assert page._table.visible_count == 1
        assert page._table.visible_rows()[0].status is ReservationStatus.CANCELLED

        page._status_combo.setCurrentIndex(0)  # Tumu
        assert page._table.visible_count == 4

    def test_tarih_suzgeci_gelecek_kayitlari_ayirir(self, page, seeded):
        index = page._period_combo.findData("future")
        page._period_combo.setCurrentIndex(index)

        numbers = {row.confirmation_number for row in page._table.visible_rows()}
        assert seeded["past"].confirmation_number not in numbers
        assert seeded["confirmed"].confirmation_number in numbers

    def test_bos_sonucta_empty_state_gorunur(self, page):
        page.set_search_query("boyle-bir-kayit-yok")
        assert page._table.visible_count == 0
        assert page._stack.currentIndex() == 1  # suzgec sonucu bos

    def test_hic_kayit_yoksa_farkli_empty_state_gorunur(self, qtbot, ui_session):
        screen = ReservationsPage(ui_session)
        qtbot.addWidget(screen)
        screen.on_shown()
        assert screen._table.total_count == 0
        assert screen._stack.currentIndex() == 2  # hic veri yok


# --------------------------------------------------------------------------
#  Ekran: ayrinti ve eylemler
# --------------------------------------------------------------------------
class TestAyrintiVeEylemler:
    def test_secim_ayrinti_panelini_doldurur(self, page, seeded):
        row = find_row(page, seeded["confirmed"].confirmation_number)
        page._show_detail(row)

        assert page._detail_stack.currentIndex() == 1
        assert page._detail_number.text() == row.confirmation_number
        assert page._detail_badge.text() == "Onaylandi"
        assert "101" in page._detail_rooms.text()
        assert "2.000,00" in page._detail_amounts.text()

    def test_cift_tiklama_ayrinti_acar(self, page, seeded):
        row = find_row(page, seeded["tentative"].confirmation_number)
        page._table.row_activated.emit(row)
        assert page._detail_stack.currentIndex() == 1
        assert page._detail_number.text() == row.confirmation_number

    def test_dugme_etkinlikleri_available_actions_ile_uyumlu(self, page):
        for row in page._table.model.rows:
            page._show_detail(row)
            actions = available_actions(row.status)
            assert page._confirm_button.isEnabled() is actions["confirm"]
            assert page._cancel_button.isEnabled() is actions["cancel"]
            assert page._no_show_button.isEnabled() is actions["mark_no_show"]

    def test_opsiyonlu_rezervasyonda_onayla_etkin(self, page, seeded):
        page._show_detail(find_row(page, seeded["tentative"].confirmation_number))
        assert page._confirm_button.isEnabled()
        assert page._cancel_button.isEnabled()
        assert page._no_show_button.isEnabled()

    def test_iptal_edilmis_rezervasyonda_tum_dugmeler_pasif(self, page, seeded):
        page._show_detail(find_row(page, seeded["cancelled"].confirmation_number))
        assert not page._confirm_button.isEnabled()
        assert not page._cancel_button.isEnabled()
        assert not page._no_show_button.isEnabled()
        assert "durum degisikligi yapilamaz" in page._action_hint.text()

    def test_secim_yokken_dugmeler_pasif(self, page):
        page._show_detail(None)
        assert page._detail_stack.currentIndex() == 0
        assert not page._confirm_button.isEnabled()

    def test_yetkisiz_kullanicida_yeni_rezervasyon_dugmesi_pasif(self, qtbot, viewer_ui_session):
        screen = ReservationsPage(viewer_ui_session)
        qtbot.addWidget(screen)
        assert not screen._new_button.isEnabled()

    def test_iptal_gerekce_alir_ve_ucreti_gosterir(self, page, seeded, patched_scope, monkeypatch):
        notices: list[tuple[str, str]] = []
        monkeypatch.setattr(page_module, "confirm", lambda *a, **k: True)
        monkeypatch.setattr(
            ReservationsPage,
            "_ask_cancellation_reason",
            lambda self, row: "Ucus iptal oldu",
        )
        monkeypatch.setattr(
            ReservationsPage,
            "_show_fee_notice",
            lambda self, title, message: notices.append((title, message)),
        )

        target = seeded["confirmed"]
        page._show_detail(find_row(page, target.confirmation_number))
        page._on_cancel()

        stored = patched_scope.get(Reservation, target.id)
        assert stored.status is ReservationStatus.CANCELLED
        assert stored.cancellation_reason == "Ucus iptal oldu"
        assert notices, "Iptal ucreti kullaniciya gosterilmedi."
        assert "iptal ucreti" in notices[0][1].lower()

    def test_gerekce_verilmezse_iptal_yapilmaz(self, page, seeded, patched_scope, monkeypatch):
        monkeypatch.setattr(page_module, "confirm", lambda *a, **k: True)
        monkeypatch.setattr(page_module, "show_error", lambda *a, **k: None)
        monkeypatch.setattr(ReservationsPage, "_ask_cancellation_reason", lambda self, row: None)

        target = seeded["confirmed"]
        page._show_detail(find_row(page, target.confirmation_number))
        page._on_cancel()

        assert patched_scope.get(Reservation, target.id).status is ReservationStatus.CONFIRMED

    def test_gelmedi_isaretleme_ucreti_gosterir(self, page, seeded, patched_scope, monkeypatch):
        notices: list[tuple[str, str]] = []
        monkeypatch.setattr(page_module, "confirm", lambda *a, **k: True)
        monkeypatch.setattr(
            ReservationsPage,
            "_show_fee_notice",
            lambda self, title, message: notices.append((title, message)),
        )

        target = seeded["confirmed"]
        page._show_detail(find_row(page, target.confirmation_number))
        page._on_no_show()

        assert patched_scope.get(Reservation, target.id).status is ReservationStatus.NO_SHOW
        assert "ceza ucreti" in notices[0][1].lower()


# --------------------------------------------------------------------------
#  Diyalog
# --------------------------------------------------------------------------
class TestRezervasyonDiyalogu:
    def test_musaitlik_aramasi_sonuc_dondurur(self, dialog):
        start = utcnow().date() + timedelta(days=20)
        set_dates(dialog, start, start + timedelta(days=3))
        dialog.search_availability()

        rows = dialog._availability_table.model.rows
        assert rows, "Musaitlik sonucu bos dondu."
        assert rows[0].available_count == 3
        assert rows[0].total is not None
        assert "3 oda musait" in rows[0].availability_text()

    def test_musait_olmayan_tip_gizlenmez(self, dialog, seeded):
        # seeded fiksturu 101/102 odalarini, 103'u iptal edilmis rezervasyonla
        # doldurdu; kalan odayi da doldurup tipin tamamen dolmasini sagliyoruz.
        start = utcnow().date() + timedelta(days=7)
        with dialog.ui.service_context() as ctx:
            from app.infrastructure.db.models.rooms import Room

            room = ctx.session.scalars(select(Room).where(Room.number == "103")).one()
            ReservationService(ctx).create_reservation(
                guest_id=seeded["confirmed"].primary_guest_id,
                room_requests=[
                    RoomRequest(
                        room_type_id=room.room_type_id,
                        room_id=room.id,
                        check_in=start,
                        check_out=start + timedelta(days=2),
                    )
                ],
            )

        set_dates(dialog, start, start + timedelta(days=2))
        dialog.search_availability()

        rows = dialog._availability_table.model.rows
        assert len(rows) == 1, "Musait olmayan oda tipi listeden dusurulmus."
        assert rows[0].availability_text() == "Musait degil"
        assert not rows[0].is_selectable
        assert not dialog._save_button.isEnabled()

    def test_kapasite_yetersizse_neden_yazilir(self, dialog):
        start = utcnow().date() + timedelta(days=30)
        set_dates(dialog, start, start + timedelta(days=2))
        dialog._adults.setValue(4)  # oda tipi en fazla 3 kisilik
        dialog.search_availability()

        rows = dialog._availability_table.model.rows
        assert len(rows) == 1
        assert "Kapasite yetersiz" in rows[0].availability_text()
        assert not rows[0].is_selectable

    def test_gecersiz_tarih_alani_isaretlenir(self, dialog, monkeypatch):
        monkeypatch.setattr(dialog_module, "show_error", lambda *a, **k: None)
        start = utcnow().date() + timedelta(days=10)
        set_dates(dialog, start, start)  # cikis = giris

        dialog.search_availability()

        assert dialog._check_out.property("invalid") is True
        assert "Cikis tarihi" in dialog._error_label.text()

    def test_oda_tipi_secilince_fiyat_dokumu_gosterilir(self, dialog):
        start = utcnow().date() + timedelta(days=25)
        set_dates(dialog, start, start + timedelta(days=2))
        dialog.search_availability()
        option = select_first_available(dialog)

        assert dialog._selected_option is option
        assert dialog._save_button.isEnabled()
        assert dialog._room_combo.count() == 4  # "Farketmez" + 3 oda

        texts = price_lines(dialog)
        assert any("TOPLAM" in text for text in texts)
        assert any("Oda ucreti" in text for text in texts)
        assert any("Ortalama gecelik ucret" in text for text in texts)

    def test_yeni_misafir_ile_rezervasyon_olusturulur(self, dialog, patched_scope):
        start = utcnow().date() + timedelta(days=40)
        set_dates(dialog, start, start + timedelta(days=2))
        dialog.search_availability()
        select_first_available(dialog)

        dialog._guest_tabs.setCurrentIndex(1)
        dialog._first_name.setText("Yaren")
        dialog._last_name.setText("Kilicaslan")
        dialog._phone.setText("+90 5XX XXX XX 09")
        dialog._deposit.setText("1.000,00")

        dialog._save()

        assert dialog.created_confirmation is not None
        assert dialog.created_confirmation.startswith("RZV")
        stored = patched_scope.get(Reservation, dialog.created_reservation_id)
        assert stored.deposit_amount == Decimal("1000.00")
        assert stored.primary_guest.full_name == "Yaren Kilicaslan"

    def test_mevcut_misafir_aramasi_sonuc_listeler(self, dialog, seeded):
        dialog.search_guests("Deniz")
        assert dialog._guest_list.count() == 1
        assert "Deniz Yildizli" in dialog._guest_list.item(0).text()

    def test_misafir_secilmeden_kayit_engellenir(self, dialog, monkeypatch):
        monkeypatch.setattr(dialog_module, "show_error", lambda *a, **k: None)
        start = utcnow().date() + timedelta(days=45)
        set_dates(dialog, start, start + timedelta(days=2))
        dialog.search_availability()
        select_first_available(dialog)

        dialog._save()

        assert dialog.created_confirmation is None
        assert "misafir" in dialog._error_label.text().lower()

    def test_cakisma_hatasi_anlasilir_gosterilir(self, dialog, seeded, monkeypatch):
        shown: list[Exception] = []
        monkeypatch.setattr(
            dialog_module, "show_error", lambda parent, error, **k: shown.append(error)
        )

        def explode(*args, **kwargs):
            raise OverlappingReservationError(
                "Bu odada 10.09.2026 - 12.09.2026 (2 gece) tarihlerinde "
                "RZV-2026-000001 numarali rezervasyon bulunuyor."
            )

        monkeypatch.setattr(ReservationService, "create_reservation", explode)

        start = utcnow().date() + timedelta(days=50)
        set_dates(dialog, start, start + timedelta(days=2))
        dialog.search_availability()
        select_first_available(dialog)
        dialog._guest_tabs.setCurrentIndex(1)
        dialog._first_name.setText("Test")
        dialog._last_name.setText("Misafir")

        dialog._save()

        assert dialog.created_confirmation is None
        assert dialog.result() != ReservationDialog.DialogCode.Accepted
        assert shown and isinstance(shown[0], OverlappingReservationError)
        assert "RZV-2026-000001" in dialog._error_label.text()

    def test_gecersiz_depozito_alani_isaretlenir(self, dialog, monkeypatch):
        monkeypatch.setattr(dialog_module, "show_error", lambda *a, **k: None)
        start = utcnow().date() + timedelta(days=55)
        set_dates(dialog, start, start + timedelta(days=2))
        dialog.search_availability()
        select_first_available(dialog)
        dialog._deposit.setText("bes yuz")

        dialog._save()

        assert dialog._deposit.property("invalid") is True
        assert dialog.created_confirmation is None


class TestTutarAyristirma:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("", "0.00"),
            ("1.250,50", "1250.50"),
            ("750", "750.00"),
            ("1250.50", "1250.50"),
            (" 400,00 ₺ ", "400.00"),
        ],
    )
    def test_turkce_tutar_bicimleri_okunur(self, text, expected):
        assert str(parse_amount(text, field="deposit_amount")) == expected

    def test_negatif_tutar_reddedilir(self):
        from app.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            parse_amount("-10", field="deposit_amount")


# --------------------------------------------------------------------------
#  Gorunum kusurlarina karsi gerileme testleri
# --------------------------------------------------------------------------
class TestGorunumGerilemeleri:
    """Render incelemesinde bulunup duzeltilen kusurlari sabitler.

    Bu testlerin hepsi *gorulmus* bir kusuru korur; hicbiri varsayimsal
    degildir. Renk/konum iddialari piksel yerine bilesen agacindan
    dogrulanir - boylece tema degistiginde test kirilmaz.
    """

    def test_fiyat_dokumu_kaydirma_alaninin_disindadir(self, dialog):
        """Toplam, pencere kaydirilmadan da gorunur olmali.

        Bolumleri yan yana dizmek yetmiyordu: icerik goruntulenen alani
        asiyor ve kullanici toplami hic gormeden Kaydet'e basabiliyordu.
        """
        from PySide6.QtWidgets import QScrollArea

        scroll = dialog.findChild(QScrollArea)
        price_card = dialog._price_layout.parentWidget()

        assert scroll is not None
        # Fiyat karti kaydirma alaninin cocugu OLMAMALI.
        assert not scroll.isAncestorOf(price_card)
        # Buna karsilik 4. bolum kaydirma alaninin icinde kalir.
        assert scroll.isAncestorOf(dialog._deposit)

    def test_fiyat_dokumu_yenilenince_eski_satirlar_kalmaz(self, dialog):
        """Eski ipucu metni yeni fiyat satirinin uzerine binmemeli.

        ``deleteLater`` silmeyi olay dongusune erteler; bilesen o ana kadar
        ust bilesenin cocugu olarak eski konumunda cizilmeye devam eder.
        """
        holder = dialog._price_layout.parentWidget()
        before = {child.text() for child in holder.findChildren(QLabel)}
        assert any("fiyat dokumu burada cikar" in text for text in before)

        start = utcnow().date() + timedelta(days=60)
        set_dates(dialog, start, start + timedelta(days=2))
        dialog.search_availability()
        select_first_available(dialog)

        after = {child.text() for child in holder.findChildren(QLabel)}
        assert any("TOPLAM" in text for text in after)
        # Yer tutucu metin agactan tamamen kalkmis olmali.
        assert not any("fiyat dokumu burada cikar" in text for text in after)

    def test_bos_durum_panelleri_kart_yuzeyinde_saydamdir(self, page):
        """Kartin ortasinda koyu dikdortgen birakmamali.

        Genel ``QWidget`` kurali her duz kapsayiciyi sayfa zeminiyle boyar;
        yigin ve bos durum paneli saydamlastirilmazsa kart uzerinde bir
        "delik" gorunur.
        """
        for widget in (page._stack, page._detail_stack):
            assert "transparent" in widget.styleSheet()

        for index in (1, 2):
            empty = page._stack.widget(index)
            assert "transparent" in empty.styleSheet()
            for label in empty.findChildren(QLabel):
                assert "transparent" in label.styleSheet()

    def test_saydamlik_kurali_nesne_adiyla_sinirlidir(self):
        """Secicisiz stil alt bilesenlere miras kalir - rozeti de bozardi."""
        from PySide6.QtWidgets import QWidget

        widget = page_module.transparent_panel(QWidget(), "OrnekPanel")

        assert widget.objectName() == "OrnekPanel"
        assert widget.styleSheet() == "#OrnekPanel { background: transparent; }"

    def test_pasif_dugme_vurgu_nesne_adini_birakir(self, page, seeded):
        """Pasif dugme dolu renkte gorunmemeli.

        Stil sayfasinda ``#Primary``/``#Danger`` icin ``:disabled`` karsiligi
        yok; nesne adi pasifken de dururasa dugme tiklanabilir gorunur.
        """
        page._show_detail(find_row(page, seeded["cancelled"].confirmation_number))

        for button in (page._confirm_button, page._cancel_button):
            assert not button.isEnabled()
            assert button.objectName() == ""

        page._show_detail(find_row(page, seeded["confirmed"].confirmation_number))
        assert page._cancel_button.isEnabled()
        assert page._cancel_button.objectName() == "Danger"
