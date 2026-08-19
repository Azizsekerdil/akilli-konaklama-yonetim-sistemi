"""Raporlar ve Yapay Zeka Merkezi ekranlarinin testleri.

Testler gercek Qt bilesenleri ve bellek ici bir veritabani kullanir.
``UiSession.service_context`` testin oturumuna baglanir; boylece ekranin
yazdigini test dogrudan gorebilir.

Burada sinanan davranislar:

* Ekranlar **cokmeden** kurulur ve ilk raporu uretir.
* **Bos veride** tablo yerine :class:`~app.ui.widgets.common.EmptyState`
  gosterilir.
* **Mali raporlar** yetkisi olmayan kullanicinin listesinde hic gorunmez ve
  ADR/RevPAR kartlari maskelenir.
* **Disa aktarma** yetkisi olmayanda dugmeler pasiftir; yetkili kullanicida
  dosya gercekten uretilir.
* **Her yapay zeka yaniti** :class:`~app.ui.widgets.common.AiBadge` ile
  isaretlidir; fiyat onerisinde uyari zorunlu, uygulama dugmesi YOKTUR.

``QT_QPA_PLATFORM=offscreen`` kok ``conftest.py`` icinde ayarlidir.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal

import pytest
from PySide6.QtWidgets import QLabel, QPushButton, QToolButton

from app.application.services.ai_service import (
    PRICING_ADVISORY_NOTE,
    AIDraft,
    AIResult,
    DraftKind,
    PricingSuggestion,
    PricingSuggestionItem,
    ReviewClassification,
)
from app.core import paths
from app.domain.enums import AITaskType, Currency
from app.domain.value_objects import DateRange, Money
from app.security.permissions import Perm
from app.ui.pages.ai_center_page import AICenterPage
from app.ui.pages.reports_page import (
    REPORT_KINDS,
    ReportsPage,
    _stretch_column_index,
    format_period,
)
from app.ui.session import UiSession
from app.ui.widgets.common import AiBadge, EmptyState

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
def ui_session(patched_scope, admin_user, sample_property, sample_room_type, sample_rooms):
    """Tum yetkilere sahip arayuz oturumu."""
    session = UiSession(user=admin_user, token="test")
    session.set_property(sample_property.id, sample_property.name)
    return session


@pytest.fixture
def frontdesk_ui(patched_scope, frontdesk_user, sample_property, sample_rooms):
    """On buro kullanicisi: rapor gorur, MALI rapor ve disa aktarma yetkisi YOK."""
    session = UiSession(user=frontdesk_user, token="test")
    session.set_property(sample_property.id, sample_property.name)
    return session


@pytest.fixture
def export_dir(tmp_path, monkeypatch):
    """Disa aktarma kokunu gecici klasore tasir (gercek exports/ klasorune dokunmaz)."""
    data_root = tmp_path / "veri"
    exports = data_root / "exports"
    exports.mkdir(parents=True)
    monkeypatch.setattr(paths, "DATA_ROOT", data_root)
    monkeypatch.setattr(paths, "EXPORT_DIR", exports)
    return exports


@pytest.fixture
def sessiz_bildirimler(monkeypatch):
    """Modal kutulari susturur; aksi halde test kullanici girdisi bekler."""
    kayit: list[str] = []
    monkeypatch.setattr(
        "app.ui.pages.reports_page.show_error",
        lambda *args, **kwargs: kayit.append("error"),
    )
    monkeypatch.setattr(
        "app.ui.pages.reports_page.show_toast",
        lambda *args, **kwargs: kayit.append("toast"),
    )
    monkeypatch.setattr(
        "app.ui.pages.ai_center_page.show_error",
        lambda *args, **kwargs: kayit.append("error"),
    )
    monkeypatch.setattr(
        "app.ui.pages.ai_center_page.show_toast",
        lambda *args, **kwargs: kayit.append("toast"),
    )
    return kayit


# --------------------------------------------------------------------------
#  Yardimcilar
# --------------------------------------------------------------------------
def kind_titles(page: ReportsPage) -> list[str]:
    return [page._kind_list.item(row).text() for row in range(page._kind_list.count())]


def select_kind(page: ReportsPage, title: str) -> None:
    for row in range(page._kind_list.count()):
        if page._kind_list.item(row).text() == title:
            page._kind_list.setCurrentRow(row)
            return
    raise AssertionError(f"Rapor turu listede yok: {title}")


def sonuc(content: str = "Ornek yanit", reasoning: str = "") -> AIResult:
    """Ag cagrisi yapmadan uretilmis ornek yapay zeka sonucu."""
    return AIResult(
        content=content,
        task_type=AITaskType.DAILY_SUMMARY,
        reasoning=reasoning,
        model="mock-echo-1",
        provider="mock",
        prompt_tokens=100,
        completion_tokens=50,
        reasoning_tokens=10 if reasoning else 0,
        total_tokens=150,
        latency_ms=1200,
        estimated_cost=Decimal("0.000000"),
        cost_currency=Currency.USD,
    )


def chat_widget(page: AICenterPage):
    """Sohbet alanindaki kaydirilabilir icerik bileseni."""
    return page._scroll.widget()


# ==========================================================================
#  Raporlar ekrani
# ==========================================================================
class TestRaporlarEkrani:
    def test_ekran_kurulur_ve_ilk_rapor_uretilir(self, qtbot, ui_session):
        page = ReportsPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()

        assert kind_titles(page) == [k.title for k in REPORT_KINDS]
        assert page._table is not None
        assert page._table.title == "Doluluk Raporu"
        # Uc oda x donem gunu kadar satir bekleniyor; tablo cizilmis olmali.
        assert page._table_view is not None
        assert page._table_view.total_count > 0

    def test_bos_raporda_cokmez_ve_bos_durum_gosterilir(
        self, qtbot, ui_session, sessiz_bildirimler
    ):
        page = ReportsPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()

        # Stok karti hic tanimlanmadi -> rapor bos doner.
        select_kind(page, "Stok")
        page._on_generate_clicked()

        assert page._table is not None
        assert page._table.is_empty
        assert page._table_view is None
        assert page.findChild(EmptyState) is not None
        assert page._row_count_label.text() == "0 satir"
        assert "error" not in sessiz_bildirimler

    def test_mali_raporlar_yetkisiz_kullanicida_listede_yok(self, qtbot, frontdesk_ui):
        assert frontdesk_ui.can(Perm.REPORT_VIEW)
        assert not frontdesk_ui.can(Perm.REPORT_FINANCIAL)

        page = ReportsPage(frontdesk_ui)
        qtbot.addWidget(page)
        page.on_shown()

        titles = kind_titles(page)
        for gizli in ("Gelir (Kanal)", "Gelir (Oda Tipi)", "Gun Sonu Kapanis", "KPI Ozeti"):
            assert gizli not in titles
        assert "Doluluk" in titles

    def test_mali_kpi_kartlari_yetkisiz_kullanicida_maskelenir(self, qtbot, frontdesk_ui):
        page = ReportsPage(frontdesk_ui)
        qtbot.addWidget(page)
        page.on_shown()

        assert page._kpis["adr"]._value.text() == "-"
        assert page._kpis["revpar"]._value.text() == "-"
        # Doluluk mali bir gosterge degildir; gorunmeye devam etmeli.
        assert page._kpis["occupancy"]._value.text() != "-"

    def test_disa_aktarma_yetkisi_yoksa_dugmeler_pasif(self, qtbot, frontdesk_ui):
        assert not frontdesk_ui.can(Perm.REPORT_EXPORT)

        page = ReportsPage(frontdesk_ui)
        qtbot.addWidget(page)
        page.on_shown()

        assert page._export_buttons
        assert all(not button.isEnabled() for button in page._export_buttons)

    def test_csv_disa_aktarilir_ve_yolu_bildirilir(
        self, qtbot, ui_session, export_dir, sessiz_bildirimler
    ):
        page = ReportsPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()

        page._on_export("csv")

        files = list(export_dir.glob("*.csv"))
        assert len(files) == 1
        assert files[0].name.startswith("doluluk-")
        assert page._open_folder_button.isEnabled()
        assert "toast" in sessiz_bildirimler

    def test_dosya_adi_ascii_ve_tarihli(self, qtbot, ui_session):
        page = ReportsPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()

        name = page._export_filename("csv", ".csv")
        assert name.isascii()
        assert name.endswith(".csv")

    def test_bitis_tarihi_dahil_edilerek_yorumlanir(self, qtbot, ui_session):
        """Ekranda secilen bitis gunu rapora **dahildir**."""
        page = ReportsPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()
        page._set_dates(date(2026, 8, 1), date(2026, 8, 15))

        araligi = page._selected_range()

        assert araligi.start == date(2026, 8, 1)
        assert araligi.end == date(2026, 8, 16)
        assert araligi.nights == 15

    def test_tek_gunluk_raporda_bitis_tarihi_yok_sayilir(
        self, qtbot, ui_session, sessiz_bildirimler
    ):
        """Kullanilmayan bitis alani, tek gunluk raporu engellememelidir."""
        page = ReportsPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()
        select_kind(page, "Giris - Cikis")
        # Bitis, baslangictan ONCE: alan pasif oldugu icin okunmamalidir.
        page._set_dates(date(2026, 8, 20), date(2026, 8, 1))

        page._on_generate_clicked()

        assert "error" not in sessiz_bildirimler
        assert page._table is not None
        assert page._table.title == "Giris - Cikis Raporu"
        assert not page._end_edit.isEnabled()

    def test_ters_tarih_araligi_hata_verir(self, qtbot, ui_session, sessiz_bildirimler):
        page = ReportsPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()
        page._set_dates(date(2026, 8, 20), date(2026, 8, 1))

        page._on_generate_clicked()

        assert "error" in sessiz_bildirimler

    def test_kpi_tablosundaki_donem_satiri_baslikla_ayni_tarihi_yazar(self, qtbot, ui_session):
        """Ayni ekranda iki farkli bitis tarihi gorunmemelidir.

        Rapor motoru donemi yari acik yazar ("01.08.2026 - 16.08.2026"); ekran
        basligi ise kullanicinin sectigi dahil edici araligi gosterir. Tablonun
        "Donem" satiri duzeltilmezse kullanici raporun bir gun fazlasini
        kapsadigina inanir.
        """
        page = ReportsPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()
        page._set_dates(date(2026, 8, 1), date(2026, 8, 15))
        select_kind(page, "KPI Ozeti")
        page._on_generate_clicked()

        donem = next(r for r in page._table.rows if r["gosterge"] == "Donem")

        beklenen = format_period(page._selected_range())
        assert donem["deger"] == beklenen
        assert "15 Agustos 2026" in donem["deger"]
        assert "16" not in donem["deger"]
        # Disa aktarilan dosya da ayni metni tasimalidir.
        assert page._table.filters_description == beklenen

    def test_esnetilen_sutun_icerigi_en_uzun_metin_sutunudur(self, qtbot, ui_session):
        """Dar bir sutunu esnetmek onu kirpiyordu (Giris-Cikis'ta "Tu...").

        Gun Sonu raporunda ilk metin sutunu "Grup"tur ve yalnizca "Ozet" /
        "Gelir" degerlerini tasir; ekranin yarisini kaplamamalidir. Esnetme
        asil bilgiyi tasiyan "Kalem" sutununa gitmelidir.
        """
        page = ReportsPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()
        select_kind(page, "Gun Sonu Kapanis")
        page._on_generate_clicked()

        index = _stretch_column_index(page._table)

        assert index is not None
        assert page._table.columns[index].key == "kalem"

    def test_saga_hizali_sutun_esnetilmez(self, qtbot, ui_session):
        """Saga hizali icerik sag kenara yapisir; esnetme ortada bosluk acar."""
        page = ReportsPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()
        select_kind(page, "KPI Ozeti")
        page._on_generate_clicked()

        index = _stretch_column_index(page._table)

        assert index is not None
        assert page._table.columns[index].align != "right"
        assert page._table.columns[index].key == "gosterge"

    def test_arama_satir_sayisini_gunceller(self, qtbot, ui_session):
        page = ReportsPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()
        toplam = page._table_view.total_count

        page._on_search("bulunamayacak-metin")

        assert page._table_view.visible_count == 0
        assert "suzuldu" in page._row_count_label.text()
        assert toplam > 0


# ==========================================================================
#  Yapay Zeka Merkezi ekrani
# ==========================================================================
class TestYapayZekaMerkezi:
    def test_ekran_kurulur(self, qtbot, ui_session):
        page = AICenterPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()

        assert page._task_buttons.keys() >= {"daily", "occupancy", "pricing", "draft", "review"}
        assert page._model_combo.count() >= 1

    def test_yapay_zeka_kapaliyken_durum_ve_cozum_gosterilir(self, qtbot, ui_session):
        """Test ortaminda HOTEL_AI_ENABLED=false; ekran cozum onerisi gostermeli."""
        page = AICenterPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()

        assert page._ai_enabled is False
        bos = page.findChild(EmptyState)
        assert bos is not None
        metinler = " ".join(label.text() for label in bos.findChildren(QLabel))
        assert "kapali" in metinler.lower()
        assert "Ayarlar" in metinler
        assert not page._send_button.isEnabled()

    def test_ai_yaniti_ai_rozetiyle_isaretlenir(self, qtbot, ui_session):
        page = AICenterPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()

        page._add_user_message("Gunluk ozet istendi.")
        page._add_result_message(sonuc("Bugun doluluk %72."))

        rozetler = chat_widget(page).findChildren(AiBadge)
        assert len(rozetler) == 1, "Her yapay zeka yaniti tam bir AiBadge tasimali."

    def test_dusunme_metni_varsayilan_kapali(self, qtbot, ui_session):
        page = AICenterPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()

        page._add_result_message(sonuc("Yanit", reasoning="Once dolulugu hesapladim."))

        toggle = chat_widget(page).findChild(QToolButton)
        assert toggle is not None
        assert toggle.text() == "Modelin akil yurutmesi"
        assert toggle.isChecked() is False
        gizli = [
            label
            for label in chat_widget(page).findChildren(QLabel)
            if label.text() == "Once dolulugu hesapladim."
        ]
        assert gizli and gizli[0].isHidden()

        toggle.setChecked(True)
        assert not gizli[0].isHidden()

    def test_yanit_altinda_model_sure_jeton_maliyet_gosterilir(self, qtbot, ui_session):
        page = AICenterPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()

        page._add_result_message(sonuc("Yanit"))

        metinler = [label.text() for label in chat_widget(page).findChildren(QLabel)]
        olcum = next(t for t in metinler if "jeton" in t)
        assert "mock-echo-1" in olcum
        assert "1,2 sn" in olcum
        assert "maliyet" in olcum

    def test_fiyat_onerisinde_uyari_var_uygulama_dugmesi_yok(self, qtbot, ui_session):
        page = AICenterPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()

        bugun = date(2026, 9, 1)
        oneri = PricingSuggestion(
            date_range=DateRange(bugun, bugun + timedelta(days=7)),
            summary="Hafta sonu talep guclu.",
            items=(
                PricingSuggestionItem(
                    day=bugun,
                    room_type="Standart Oda",
                    current_rate=Money.of(Decimal("1000")),
                    suggested_rate=Money.of(Decimal("1200")),
                    rationale="Doluluk yuksek.",
                ),
            ),
            result=sonuc("..."),
        )
        page._add_pricing_message(oneri)

        metinler = [label.text() for label in chat_widget(page).findChildren(QLabel)]
        assert PRICING_ADVISORY_NOTE in metinler
        assert oneri.applied is False
        # Fiyati uygulayacak hicbir dugme bulunmamalidir.
        assert chat_widget(page).findChildren(QPushButton) == []

    def test_taslak_ai_notuyla_gosterilir(self, qtbot, ui_session):
        page = AICenterPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()

        taslak = AIDraft(
            kind=DraftKind.COMPLAINT_RESPONSE,
            body="Sayin misafirimiz, ozur dileriz.",
            result=sonuc("..."),
        )
        page._add_draft_message(taslak)

        metinler = " ".join(label.text() for label in chat_widget(page).findChildren(QLabel))
        assert "gonderilmedi" in metinler
        assert "yapay zeka tarafından oluşturulmuştur" in metinler
        assert chat_widget(page).findChildren(AiBadge)

    def test_yorum_analizi_rozetlerle_gosterilir(self, qtbot, ui_session):
        page = AICenterPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()

        page._add_review_message(
            ReviewClassification(
                sentiment="olumsuz",
                score=-0.8,
                categories=("temizlik",),
                summary="Oda kirliydi.",
                is_urgent=True,
                result=sonuc("..."),
            )
        )

        metinler = [label.text() for label in chat_widget(page).findChildren(QLabel)]
        assert "Duygu: olumsuz" in metinler
        assert "Acil mudahale" in metinler
        assert "temizlik" in metinler

    def test_hata_mesajinda_cozum_onerisi_gosterilir(self, qtbot, ui_session, sessiz_bildirimler):
        from app.core.exceptions import AIConnectionError

        page = AICenterPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()
        page._active_token = 7

        page._on_job_failed(
            7,
            AIConnectionError(provider="lmstudio", remedy="LM Studio sunucusunu baslatin."),
        )

        metinler = " ".join(label.text() for label in chat_widget(page).findChildren(QLabel))
        assert "LM Studio sunucusunu baslatin." in metinler
        assert page._active_token is None

    def test_iptal_arayuzu_serbest_birakir_ve_durustce_bilgilendirir(self, qtbot, ui_session):
        page = AICenterPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()
        page._active_token = 3
        page._set_busy(True, "gunluk")

        page._on_cancel()

        assert page._active_token is None
        assert not page._busy_bar.isVisible()
        metinler = " ".join(label.text() for label in chat_widget(page).findChildren(QLabel))
        assert "iptal edildi" in metinler.lower()
        assert "kullanim kaydi" in metinler.lower()

    def test_iptal_sonrasi_gelen_yanit_gosterilmez(self, qtbot, ui_session):
        page = AICenterPage(ui_session)
        qtbot.addWidget(page)
        page.on_shown()
        page._active_token = 11
        page._on_cancel()
        onceki = len(chat_widget(page).findChildren(AiBadge))

        # Gecikmis yanit eski istek numarasiyla gelir.
        page._on_job_finished(11, "text", sonuc("Gec gelen yanit"))

        assert len(chat_widget(page).findChildren(AiBadge)) == onceki
