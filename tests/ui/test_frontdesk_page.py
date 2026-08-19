"""On buro ekrani ve diyaloglarinin arayuz testleri.

Kapsanan kritik davranislar:

* Uc sekme de gercek veriden dolar
* Giris yapilmis rezervasyonda "Giris Yap" dugmesi pasiflesir
* Acik bakiyeli cikis satiri uyari rengiyle **ve metinle** isaretlenir
* Folyo diyalogu ucret + odeme satirlarini gosterir
* Gecersiz kilinmis ucret listede GORUNUR ama toplama katilmaz
* Yetkisi olmayan kullanicida "Gecersiz Kil" pasif kalir
* Acik bakiyeyle cikis denemesi "once tahsilat yapin" yonlendirmesi verir

Test altyapisi notu
-------------------
:class:`~app.ui.session.UiSession` normalde uygulama genelindeki motordan
oturum acar. Testlerde ``app.ui.session.session_scope`` degistirilerek
fikstur oturumu dondurulur; boylece ekran, testin bellek ici veritabanini
gorur ve gercek ``UiSession`` kod yolu (kullaniciyi yeniden yukleme dahil)
korunur.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal

import pytest
from PySide6.QtCore import Qt
from sqlalchemy.orm import Session

from app.application.context import ServiceContext
from app.application.services.folio_service import FolioService
from app.application.services.frontdesk_service import FrontdeskService
from app.application.services.reservation_service import ReservationService, RoomRequest
from app.core.exceptions import PaymentError, ValidationError
from app.domain.enums import PaymentMethod, RoomHousekeepingStatus
from app.infrastructure.db.base import utcnow
from app.ui.session import UiSession
from app.ui.theme import active_palette

pytestmark = [pytest.mark.ui, pytest.mark.integration]


# --------------------------------------------------------------------------
#  Fiksturler
# --------------------------------------------------------------------------
@pytest.fixture
def admin_ctx(secured_session: Session, admin_user, sample_property) -> ServiceContext:
    """Tum yetkilere sahip servis baglami."""
    return ServiceContext(
        session=secured_session,
        user=admin_user,
        property_id=sample_property.id,
    )


@pytest.fixture
def _patched_session_scope(monkeypatch: pytest.MonkeyPatch, secured_session: Session) -> None:
    """``UiSession`` fikstur oturumunu kullansin."""
    import app.ui.session as ui_session_module

    @contextmanager
    def fake_scope(*, commit: bool = True) -> Iterator[Session]:
        yield secured_session
        # Commit yerine flush: testin islemi sonda geri alinabilsin.
        secured_session.flush()

    monkeypatch.setattr(ui_session_module, "session_scope", fake_scope)


@pytest.fixture
def ui_session(_patched_session_scope, admin_user, sample_property) -> UiSession:
    """Yonetici yetkileriyle arayuz oturumu."""
    session = UiSession(user=admin_user, token="test")
    session.set_property(sample_property.id, sample_property.name)
    return session


@pytest.fixture
def frontdesk_ui(_patched_session_scope, frontdesk_user, sample_property) -> UiSession:
    """On buro gorevlisi oturumu - ucret gecersiz kilma yetkisi YOK."""
    session = UiSession(user=frontdesk_user, token="test-frontdesk")
    session.set_property(sample_property.id, sample_property.name)
    return session


@pytest.fixture
def arrival(admin_ctx, sample_rate_plan, sample_room_type, sample_rooms, sample_guest):
    """Bugun giris yapacak, 2 gecelik, 101 numarali odaya atanmis rezervasyon."""
    today = utcnow().date()
    return ReservationService(admin_ctx).create_reservation(
        guest_id=sample_guest.id,
        room_requests=[
            RoomRequest(
                room_type_id=sample_room_type.id,
                room_id=sample_rooms[0].id,
                check_in=today,
                check_out=today + timedelta(days=2),
            )
        ],
    )


@pytest.fixture
def departure(admin_ctx, sample_rate_plan, sample_room_type, sample_rooms, sample_guest):
    """Bugun cikis yapacak, 102 numarali odada giris yapilmis rezervasyon."""
    today = utcnow().date()
    reservation = ReservationService(admin_ctx).create_reservation(
        guest_id=sample_guest.id,
        room_requests=[
            RoomRequest(
                room_type_id=sample_room_type.id,
                room_id=sample_rooms[1].id,
                check_in=today - timedelta(days=2),
                check_out=today,
            )
        ],
    )
    FrontdeskService(admin_ctx).check_in(reservation.rooms[0].id)
    return reservation


@pytest.fixture
def page(qtbot, ui_session):
    """Yuklenmis on buro ekrani."""
    from app.ui.pages.frontdesk_page import FrontdeskPage

    widget = FrontdeskPage(ui_session)
    qtbot.addWidget(widget)
    widget.refresh(force=True)
    return widget


def _cell(table, row: int, column: int) -> str:
    """Tablodaki bir hucrenin GORUNEN metnini dondurur."""
    index = table.model.index(row, column)
    return str(table.model.data(index, Qt.ItemDataRole.DisplayRole))


def _cell_color(table, row: int, column: int):
    index = table.model.index(row, column)
    return table.model.data(index, Qt.ItemDataRole.ForegroundRole)


# --------------------------------------------------------------------------
#  Sekmeler ve veri yukleme
# --------------------------------------------------------------------------
class TestSekmeler:
    def test_uc_sekme_turkce_baslikla_acilir(self, page):
        assert page._tabs.count() == 3
        assert [page._tabs.tabText(i) for i in range(3)] == [
            "Bugunku Girisler",
            "Bugunku Cikislar",
            "Otelde",
        ]

    def test_bugunku_girisler_yuklenir(self, page, arrival):
        page.refresh(force=True)

        assert len(page.snapshot.arrivals) == 1
        assert page._arrivals_table.model.rowCount() == 1
        assert _cell(page._arrivals_table, 0, 0) == arrival.confirmation_number
        assert _cell(page._arrivals_table, 0, 3) == "101"
        assert _cell(page._arrivals_table, 0, 6) == "Bekliyor"

    def test_bugunku_cikislar_yuklenir(self, page, departure):
        page.refresh(force=True)

        assert len(page.snapshot.departures) == 1
        assert _cell(page._departures_table, 0, 0) == "102"
        assert page.snapshot.departures[0].stay_id is not None

    def test_otelde_sekmesi_yuklenir(self, page, departure, arrival):
        """Otelde listesi konaklamasi bugunu kapsayan satirlari gosterir."""
        page.refresh(force=True)

        rooms = {row.room_number for row in page.snapshot.in_house}
        # 101 bugun giris yapacak (aralik bugunu kapsar), 102 bugun cikacak
        # (yari acik aralik geregi bugun artik otelde degil).
        assert "101" in rooms
        assert page._in_house_table.model.rowCount() == len(page.snapshot.in_house)

    def test_veri_yokken_bos_durum_gosterilir(self, page):
        """Bos tablo birakilmaz; ne yapilmasi gerektigi yazilir."""
        # Yukleme HATASI da bos ekran uretir; testin onu bos veriyle
        # karistirmamasi icin once basarili yuklemeyi dogruluyoruz.
        assert page._loaded is True
        assert page.snapshot.arrivals == []
        assert page._arrivals_table.isHidden()
        assert not page._arrivals_empty.isHidden()
        assert page._departures_table.isHidden()
        assert not page._departures_empty.isHidden()


class TestKpiVeDurum:
    def test_kpi_degerleri_hesaplanir(self, page, arrival, departure):
        page.refresh(force=True)

        assert page._kpis["pending_arrivals"]._value.text() == "1"
        assert page._kpis["pending_departures"]._value.text() == "1"
        assert page.snapshot.open_balance.amount > 0
        assert "₺" in page._kpis["open_balance"]._value.text()

    def test_giris_yapilmis_rezervasyonda_dugme_pasif(self, page, arrival, admin_ctx):
        FrontdeskService(admin_ctx).check_in(arrival.rooms[0].id)
        page.refresh(force=True)

        page._arrivals_table.table.selectRow(0)

        assert page.snapshot.arrivals[0].checked_in is True
        assert _cell(page._arrivals_table, 0, 6) == "Giris yapildi"
        assert page._check_in_button.isEnabled() is False
        assert "zaten yapilmis" in page._check_in_button.toolTip()
        assert page._arrivals_badge.text() == "Giris yapildi"

    def test_bakiyesi_olan_cikista_uyari_gorunur(self, page, departure):
        """Acik bakiye hem UYARI rengiyle hem de METINLE isaretlenir."""
        page.refresh(force=True)

        text = _cell(page._departures_table, 0, 4)
        color = _cell_color(page._departures_table, 0, 4)

        assert "acik" in text
        assert color is not None
        assert color.name().lower() == active_palette().warning.lower()

        page._departures_table.table.selectRow(0)
        assert "Acik bakiye" in page._departures_badge.text()

    def test_otelde_sekmesinde_gelmemis_satir_bekleniyor_yazar(self, page, arrival):
        """``in_house()`` bugun gelecek satirlari da dondurur - ayirt edilmeli.

        Durum sutunu olmadan bu satirlar gercekten otelde olanlarla ayni
        gorunuyordu; "Otelde" basligi altinda yaniltici oluyordu.
        """
        page.refresh(force=True)

        row_index = next(
            index for index, row in enumerate(page.snapshot.in_house) if row.room_number == "101"
        )
        assert _cell(page._in_house_table, row_index, 5) == "Bekleniyor"
        assert _cell_color(page._in_house_table, row_index, 5) is not None

    def test_cikis_sekmesinde_durum_sutunu_konaklamayi_gosterir(self, page, departure):
        page.refresh(force=True)

        assert _cell(page._departures_table, 0, 5) == "Otelde"
        # Giris yapilmis satirda durum rengi notr kalir; renk yalnizca dikkat
        # gerektiren satirlarda kullanilir.
        assert _cell_color(page._departures_table, 0, 5) is None

    def test_otelde_kpi_yalnizca_giris_yapmislari_sayar(self, page, arrival, admin_ctx):
        """Kart, otelde OLMAYAN misafirleri saymamalidir."""
        page.refresh(force=True)
        bekleyen = [row for row in page.snapshot.in_house if not row.checked_in]
        assert bekleyen, "fikstur bugun gelecek bir satir uretmeli"

        assert page._kpis["in_house"]._value.text() == "0"
        assert "bekleniyor" in page._kpis["in_house"]._delta.text()

        FrontdeskService(admin_ctx).check_in(arrival.rooms[0].id)
        page.refresh(force=True)

        assert page._kpis["in_house"]._value.text() == "1"

    def test_folyosu_olmayan_satirda_sifir_yerine_tire_yazar(self, page, arrival):
        """Giris yapilmamis satirda '0,00' yazmak 'hesap kapali' izlenimi verirdi."""
        page.refresh(force=True)

        in_house = [row for row in page.snapshot.in_house if row.room_number == "101"]
        assert in_house and in_house[0].folio_id is None

        row_index = next(
            index for index, row in enumerate(page.snapshot.in_house) if row.room_number == "101"
        )
        assert _cell(page._in_house_table, row_index, 4) == "-"


# --------------------------------------------------------------------------
#  Giris diyalogu
# --------------------------------------------------------------------------
class TestCheckinDialog:
    def test_musait_odalar_listelenir_ve_atanan_secilir(self, qtbot, ui_session, arrival):
        from app.ui.dialogs.checkin_dialog import CheckinDialog

        dialog = CheckinDialog(ui_session, arrival.rooms[0].id)
        qtbot.addWidget(dialog)

        numbers = {option.number for option in dialog.summary.rooms}
        assert {"101", "102", "103"} <= numbers
        assert dialog._room_combo.currentData() == arrival.rooms[0].room_id
        assert dialog._save_button.isEnabled()

    def test_kirli_odada_uyari_ve_onay_kutusu_gorunur(
        self, qtbot, ui_session, arrival, sample_rooms, secured_session
    ):
        sample_rooms[0].housekeeping_status = RoomHousekeepingStatus.DIRTY
        secured_session.flush()

        from app.ui.dialogs.checkin_dialog import CheckinDialog

        dialog = CheckinDialog(ui_session, arrival.rooms[0].id)
        qtbot.addWidget(dialog)

        assert not dialog._dirty_warning.isHidden()
        assert not dialog._dirty_check.isHidden()
        assert dialog._save_button.isEnabled() is False

        dialog._dirty_check.setChecked(True)
        assert dialog._save_button.isEnabled() is True

    def test_kimlik_alani_kvkk_notu_ile_isaretli(self, qtbot, ui_session, arrival):
        from app.ui.dialogs.checkin_dialog import KVKK_NOTICE, CheckinDialog

        dialog = CheckinDialog(ui_session, arrival.rooms[0].id)
        qtbot.addWidget(dialog)

        notices = [
            child.text()
            for child in dialog.findChildren(type(dialog._dirty_warning))
            if child.text() == KVKK_NOTICE
        ]
        assert notices, "KVKK uyarisi kimlik alaninin yaninda gorunmeli"
        assert "sifreli saklanir" in KVKK_NOTICE

    def test_giris_kaydedilir_ve_folyo_acilir(self, qtbot, ui_session, arrival, admin_ctx):
        from app.ui.dialogs.checkin_dialog import CheckinDialog

        dialog = CheckinDialog(ui_session, arrival.rooms[0].id)
        qtbot.addWidget(dialog)
        dialog._identity_edit.setText("11111111110")
        dialog._on_save()

        assert dialog.stay_id is not None
        folio = FolioService(admin_ctx).folio_for_room(arrival.rooms[0].id)
        assert folio is not None
        assert folio.balance == Decimal("2000.00")


# --------------------------------------------------------------------------
#  Folyo diyalogu
# --------------------------------------------------------------------------
class TestFolioDialog:
    @pytest.fixture
    def folio_id(self, admin_ctx, arrival) -> int:
        FrontdeskService(admin_ctx).check_in(arrival.rooms[0].id)
        folio = FolioService(admin_ctx).folio_for_room(arrival.rooms[0].id)
        FolioService(admin_ctx).add_payment(
            folio.id, amount=Decimal("500.00"), method=PaymentMethod.CASH
        )
        return folio.id

    def test_ucret_ve_odeme_satirlari_gosterilir(self, qtbot, ui_session, folio_id):
        from app.ui.dialogs.folio_dialog import FolioDialog

        dialog = FolioDialog(ui_session, folio_id)
        qtbot.addWidget(dialog)

        assert dialog._charges_table.rowCount() == 2  # gece basina ayri satir
        assert dialog._payments_table.rowCount() == 1
        assert dialog.snapshot.total_charges.amount == Decimal("2000.00")
        assert dialog.snapshot.total_payments.amount == Decimal("500.00")
        assert dialog.snapshot.balance.amount == Decimal("1500.00")
        assert "1.500,00" in dialog._balance_label.text()

    def test_gecersiz_ucret_listede_gorunur_ama_toplama_katilmaz(
        self, qtbot, ui_session, admin_ctx, folio_id
    ):
        from app.infrastructure.db.repositories import FolioRepository

        folio = FolioRepository(admin_ctx.session).get_with_lines(folio_id)
        first_charge = sorted(folio.charges, key=lambda c: (c.charge_date, c.id))[0]
        FolioService(admin_ctx).void_charge(first_charge.id, reason="Yanlis islendi")

        from app.ui.dialogs.folio_dialog import FolioDialog

        dialog = FolioDialog(ui_session, folio_id)
        qtbot.addWidget(dialog)

        # SILINMIS gibi gizlenmez: satir hala listede
        assert dialog._charges_table.rowCount() == 2
        assert dialog.snapshot.charges[0].is_void is True

        item = dialog._charges_table.item(0, 1)
        assert item.font().strikeOut() is True
        assert "Yanlis islendi" in item.toolTip()

        # ...ama toplama katilmaz
        assert dialog.snapshot.total_charges.amount == Decimal("1000.00")
        assert "gecersiz satir" in dialog._balance_note.text()

    def test_yetkisiz_kullanicida_gecersiz_kil_dugmesi_pasif(self, qtbot, frontdesk_ui, folio_id):
        from app.ui.dialogs.folio_dialog import FolioDialog

        dialog = FolioDialog(frontdesk_ui, folio_id)
        qtbot.addWidget(dialog)
        dialog._charges_table.selectRow(0)

        assert dialog._void_button.isEnabled() is False
        assert "yetkisi gerekiyor" in dialog._void_button.toolTip()
        # Gizlenmez - kullanici neden yapamadigini gorebilmeli
        assert dialog._void_button.isHidden() is False
        # Yetkisi olan islemler acik kalir
        assert dialog._payment_button.isEnabled() is True

    def test_yetkili_kullanicida_secili_satirda_gecersiz_kil_acilir(
        self, qtbot, ui_session, folio_id
    ):
        from app.ui.dialogs.folio_dialog import FolioDialog

        dialog = FolioDialog(ui_session, folio_id)
        qtbot.addWidget(dialog)

        assert dialog._void_button.isEnabled() is False  # secim yok
        dialog._charges_table.selectRow(0)
        assert dialog._void_button.isEnabled() is True


# --------------------------------------------------------------------------
#  Cikis diyalogu
# --------------------------------------------------------------------------
class TestCheckoutDialog:
    @pytest.fixture
    def dialog(self, qtbot, ui_session, departure, admin_ctx):
        from app.ui.dialogs.checkout_dialog import CheckoutDialog

        stay = departure.rooms[0].stay
        widget = CheckoutDialog(ui_session, stay.id)
        qtbot.addWidget(widget)
        return widget

    def test_bakiye_ozeti_gosterilir(self, dialog):
        assert dialog.summary.balance.amount == Decimal("2000.00")
        assert "2.000,00" in dialog._balance_label.text()
        assert "once tahsilat alin" in dialog._balance_note.text()
        assert not dialog._payment_card.isHidden()

    def test_acik_bakiyeyle_cikis_anlasilir_hata_gosterir(
        self, monkeypatch: pytest.MonkeyPatch, dialog
    ):
        import app.ui.dialogs.checkout_dialog as module

        gosterilen: list[Exception] = []
        monkeypatch.setattr(module, "confirm", lambda *a, **k: True)
        monkeypatch.setattr(
            module, "show_error", lambda parent, error, **k: gosterilen.append(error)
        )

        dialog._on_checkout()

        assert len(gosterilen) == 1
        hata = gosterilen[0]
        assert isinstance(hata, PaymentError)
        assert hata.code == "checkout_open_balance"
        assert "Once tahsilat yapin" in hata.context["cozum"]

    def test_tahsilat_sonrasi_cikis_yapilir(
        self, monkeypatch: pytest.MonkeyPatch, dialog, departure, admin_ctx
    ):
        import app.ui.dialogs.checkout_dialog as module

        monkeypatch.setattr(module, "confirm", lambda *a, **k: True)
        monkeypatch.setattr(module, "show_error", lambda *a, **k: None)
        monkeypatch.setattr(module, "show_toast", lambda *a, **k: None)

        dialog._amount_edit.setText("2.000,00")
        dialog._on_collect()
        assert dialog.summary.balance.amount == Decimal("0.00")

        dialog._on_checkout()

        stay = departure.rooms[0].stay
        assert stay.actual_check_out is not None
        assert dialog.changed is True

    def test_hasar_tutari_aciklama_olmadan_girilemez(self, dialog):
        assert dialog._damage_amount_edit.isEnabled() is False

        dialog._damage_edit.setText("Kirik lamba")
        assert dialog._damage_amount_edit.isEnabled() is True

        dialog._damage_amount_edit.setText("250,00")
        dialog._damage_edit.setText("")
        assert dialog._damage_amount_edit.isEnabled() is False
        assert dialog._damage_amount_edit.text() == ""

    def test_cikis_onayi_tehlikeli_olarak_sorulur(self, monkeypatch: pytest.MonkeyPatch, dialog):
        """Cikis geri alinamaz; Enter'a basan kullanici kazara onaylamamali."""
        import app.ui.dialogs.checkout_dialog as module

        cagrilar: list[dict] = []

        def sahte_confirm(*_args, **kwargs) -> bool:
            cagrilar.append(kwargs)
            return False  # kullanici vazgecti; islem yapilmamali

        monkeypatch.setattr(module, "confirm", sahte_confirm)
        dialog._on_checkout()

        assert cagrilar, "cikis onay sormadan yapilmamali"
        assert cagrilar[0]["dangerous"] is True
        assert "geri alinamaz" in cagrilar[0]["detail"]

    def test_acik_bakiye_hatasinda_devir_secenegi_de_onerilir(
        self, monkeypatch: pytest.MonkeyPatch, dialog
    ):
        """Yetkisi olan kullaniciya ekrandaki cozum yolu da anlatilmalidir."""
        import app.ui.dialogs.checkout_dialog as module

        gosterilen: list[Exception] = []
        monkeypatch.setattr(module, "confirm", lambda *a, **k: True)
        monkeypatch.setattr(
            module, "show_error", lambda parent, error, **k: gosterilen.append(error)
        )

        assert dialog._open_balance_check.isEnabled() is True
        dialog._on_checkout()

        cozum = gosterilen[0].context["cozum"]
        assert "Once tahsilat yapin" in cozum
        assert "cari hesaba devret" in cozum

    def test_yetkisiz_kullaniciya_yapamayacagi_cozum_onerilmez(
        self, monkeypatch: pytest.MonkeyPatch, qtbot, frontdesk_ui, departure
    ):
        """Devir yetkisi olmayan kullaniciyi o yola yonlendirmek anlamsizdir."""
        import app.ui.dialogs.checkout_dialog as module
        from app.ui.dialogs.checkout_dialog import CheckoutDialog

        dialog = CheckoutDialog(frontdesk_ui, departure.rooms[0].stay.id)
        qtbot.addWidget(dialog)

        gosterilen: list[Exception] = []
        monkeypatch.setattr(module, "confirm", lambda *a, **k: True)
        monkeypatch.setattr(
            module, "show_error", lambda parent, error, **k: gosterilen.append(error)
        )
        dialog._on_checkout()

        cozum = gosterilen[0].context["cozum"]
        assert "Once tahsilat yapin" in cozum
        assert "cari hesaba devret" not in cozum


class TestYetkiKisitlariGorunur:
    """Devre disi birakilan alan, kisitini METINLE de belli etmelidir.

    Stil sayfasinda ``QSpinBox`` ve ``QCheckBox`` icin ayri bir "devre disi"
    gorunumu tanimli degil (``QLineEdit``/``QComboBox`` icin var). Yalnizca
    ``setEnabled(False)`` cagirmak, alani etkin gorunur birakiyor ve kullanici
    neden yazamadigini ancak fare ipucunda okuyabiliyordu.
    """

    def test_gec_cikis_yetkisi_yoksa_alan_bunu_yazar(self, qtbot, frontdesk_ui, departure):
        from app.ui.dialogs.checkout_dialog import CheckoutDialog

        dialog = CheckoutDialog(frontdesk_ui, departure.rooms[0].stay.id)
        qtbot.addWidget(dialog)

        assert dialog._late_spin.isEnabled() is False
        assert "Yetkiniz yok" in dialog._late_spin.text()
        assert "yetkisi gerekiyor" in dialog._late_spin.toolTip()

    def test_devir_yetkisi_yoksa_kutu_metni_bunu_yazar(self, qtbot, frontdesk_ui, departure):
        from app.ui.dialogs.checkout_dialog import CheckoutDialog

        dialog = CheckoutDialog(frontdesk_ui, departure.rooms[0].stay.id)
        qtbot.addWidget(dialog)

        assert dialog._open_balance_check.isEnabled() is False
        assert "yetkiniz yok" in dialog._open_balance_check.text().lower()


# --------------------------------------------------------------------------
#  Yerlesim: engelleyici kontroller her zaman gorunur olmali
# --------------------------------------------------------------------------
def _dibi(dialog, widget) -> int:
    """Bilesenin alt kenarinin diyalog koordinatindaki y degeri."""
    return widget.mapTo(dialog, widget.rect().bottomLeft()).y()


def _goster(qtbot, dialog) -> None:
    """Diyalogu ekrana CIKARMADAN yerlesimini hesaplatir."""
    qtbot.addWidget(dialog)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dialog.show()
    dialog.layout().activate()


class TestEngelleyiciKontrollerGorunur:
    """Bir dugmeyi kilitleyen kontrol, dugmenin yaninda gorunmelidir.

    Bu bolum gercek bir kusurun nobetcisidir: uyari ve onay kutusu
    kaydirilabilir govdedeyken diyalogun acilis yuksekliginin ALTINA
    dusuyordu. Kullanici pasif bir "Giris Yap" dugmesi goruyor, nedenini
    yalnizca fare ipucunda okuyabiliyordu.
    """

    def test_kirli_oda_uyarisi_kaydirma_alani_disinda_durur(self, qtbot, ui_session, arrival):
        from app.ui.dialogs.checkin_dialog import CheckinDialog

        dialog = CheckinDialog(ui_session, arrival.rooms[0].id)
        _goster(qtbot, dialog)

        govde = dialog._scroll.widget()
        assert dialog._dirty_warning.parent() is not govde
        assert dialog._dirty_check.parent() is not govde

    def test_kirli_odada_uyari_acilis_boyutunda_gorunur(
        self, qtbot, ui_session, arrival, sample_rooms, secured_session
    ):
        sample_rooms[0].housekeeping_status = RoomHousekeepingStatus.DIRTY
        secured_session.flush()

        from app.ui.dialogs.checkin_dialog import CheckinDialog

        dialog = CheckinDialog(ui_session, arrival.rooms[0].id)
        _goster(qtbot, dialog)

        assert dialog._save_button.isEnabled() is False
        assert _dibi(dialog, dialog._dirty_check) <= dialog.height()
        assert _dibi(dialog, dialog._dirty_warning) <= dialog.height()

    def test_acik_bakiye_devri_kutusu_acilis_boyutunda_gorunur(self, qtbot, ui_session, departure):
        """Acik bakiyeli cikisi mumkun kilan TEK kontrol gorunur olmali."""
        from app.ui.dialogs.checkout_dialog import CheckoutDialog

        dialog = CheckoutDialog(ui_session, departure.rooms[0].stay.id)
        _goster(qtbot, dialog)

        assert dialog.summary.balance.amount > 0
        assert dialog._open_balance_check.parent() is not dialog._scroll.widget()
        assert _dibi(dialog, dialog._open_balance_check) <= dialog.height()

    def test_cikis_diyalogu_icerigi_kaydirmadan_sigar(self, qtbot, ui_session, departure):
        """Ekran yeterliyse hicbir kart yarim kirpilmamali."""
        from app.ui.dialogs.checkout_dialog import CheckoutDialog

        dialog = CheckoutDialog(ui_session, departure.rooms[0].stay.id)
        _goster(qtbot, dialog)

        govde = dialog._scroll.widget()
        assert govde.sizeHint().height() <= dialog._scroll.viewport().height()


# --------------------------------------------------------------------------
#  Para bicimi
# --------------------------------------------------------------------------
class TestTutarCozumleme:
    def test_turkce_ve_nokta_bicimi_kabul_edilir(self):
        from app.ui.dialogs.folio_dialog import parse_amount

        assert parse_amount("1.250,75") == Decimal("1250.75")
        assert parse_amount("1250.75") == Decimal("1250.75")
        assert parse_amount(" 900 ₺ ") == Decimal("900.00")

    def test_gecersiz_tutar_anlasilir_hata_verir(self):
        from app.ui.dialogs.folio_dialog import parse_amount

        with pytest.raises(ValidationError):
            parse_amount("abc")
        with pytest.raises(ValidationError):
            parse_amount("")
        with pytest.raises(ValidationError):
            parse_amount("-5")
