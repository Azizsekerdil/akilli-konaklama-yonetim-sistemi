"""Yapay Zeka Merkezi ekrani.

Ekran :class:`~app.application.services.ai_service.AIService` disinda hicbir
yapay zeka kaynagina dokunmaz; istem kurma, gizlilik maskeleme, kullanim kaydi
ve hata cevirisi tumuyle servis katmanindadir. Buradaki sorumluluk yalnizca
**sunum** ve **akiskanliktir**.

Arayuz neden donmuyor?
----------------------
Yerel bir dil modeli 10-60 saniye yanit uretebilir. Cagri ana (arayuz) is
parcaciginda yapilsaydi pencere o sure boyunca kilitlenir, Windows "yanit
vermiyor" der ve kullanici uygulamayi kapatirdi. Bu yuzden her cagri
:class:`_AiJob` (bir ``QRunnable``) icinde :class:`~PySide6.QtCore.QThreadPool`
uzerinde calisir. Kurallar:

* **Veritabani oturumu is parcaciginin kendisinde acilir.** SQLAlchemy oturumu
  parcaciklar arasi paylasilamaz; ``UiSession.service_context()`` her cagrida
  yeni bir oturum uretir ve bu, calisan parcaciga ait olur.
* **ORM nesnesi disari cikmaz.** Is parcacigi yalnizca dataclass dondurur.
* **Sinyaller ekrana aittir.** ``QRunnable`` havuz tarafindan yok edilebilir;
  bu yuzden sinyal nesnesi (:class:`_AiJobSignals`) ekranin cocugudur ve
  yasam suresi ekranla ayni olur.
* **Hata baglam blogunun icinde yakalanir.** Aksi halde ``session_scope``
  geri alma yapar ve basarisiz cagrinin ``AIUsage`` kaydi da silinirdi
  (bkz. :mod:`app.application.services.ai_service` modul aciklamasi).

Iptal ne yapar, ne yapmaz
-------------------------
"Iptal" arayuzu **hemen** serbest birakir ve gelen yaniti yok sayar. Ancak
saglayiciya gonderilmis bir HTTP istegi disaridan durdurulamaz: model
uretmeye devam eder ve kullanim kaydi yazilir. Bu durustce boyle belgelenir;
"iptal edildi" deyip arka planda jeton harcamaya devam eden bir arayuz
kullaniciyi yanilttir.

Fiyat onerileri
---------------
Fiyat onerisi sonucunda ekranda **fiyati degistiren hicbir dugme yoktur**.
Sonucun ustunde :data:`~app.application.services.ai_service.PRICING_ADVISORY_NOTE`
uyarisi zorunlu olarak gosterilir.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.application.services.ai_service import (
    AI_GENERATED_MARKER,
    PRICING_ADVISORY_NOTE,
    REMEDY_AI_DISABLED,
    AIDraft,
    AIResult,
    AIService,
    DraftKind,
    PricingSuggestion,
    ReviewClassification,
)
from app.core.exceptions import HotelError
from app.core.log import get_logger
from app.domain.value_objects import DateRange
from app.infrastructure.db.base import utcnow
from app.security.permissions import Perm
from app.ui.formatting import format_datetime, format_number
from app.ui.i18n import t
from app.ui.pages.base import BasePage
from app.ui.session import UiSession
from app.ui.widgets.common import (
    AiBadge,
    Card,
    EmptyState,
    SectionTitle,
    StatusBadge,
    ToastLevel,
    show_error,
    show_toast,
)

log = get_logger(__name__)

#: Doluluk analizi varsayilan penceresi (bugunden geriye).
OCCUPANCY_WINDOW_DAYS = 30

#: Fiyat onerisi varsayilan penceresi (bugunden ileriye).
PRICING_WINDOW_DAYS = 14

#: Sohbet balonunda gosterilecek azami oneri satiri.
MAX_SUGGESTION_ROWS = 12


# ==========================================================================
#  Arka plan calistirma
# ==========================================================================
class _AiJobSignals(QObject):
    """Is parcacigindan arayuze donen sinyaller.

    Ekranin cocugu olarak olusturulur; boylece havuz ``QRunnable`` nesnesini
    yok etse bile sinyal baglantilari gecerli kalir.
    """

    finished = Signal(int, str, object)
    """(istek numarasi, sonuc turu, veri)"""

    failed = Signal(int, object)
    """(istek numarasi, istisna)"""


class _AiJob(QRunnable):
    """Tek bir yapay zeka cagrisini arka planda calistirir.

    ``job`` bir :class:`AIService` alir ve ``(tur, veri)`` ikilisi dondurur.
    Servis cagrisi **baglam blogunun icinde** yakalanir; bu, basarisiz
    cagrilarin kullanim kaydinin geri alinmamasi icin zorunludur.
    """

    def __init__(
        self,
        ui_session: UiSession,
        signals: _AiJobSignals,
        token: int,
        model: str,
        job: Callable[[AIService], tuple[str, Any]],
    ) -> None:
        super().__init__()
        # Havuz nesneyi silmesin: yasam suresini ekran yonetir.
        self.setAutoDelete(False)
        self._ui = ui_session
        self._signals = signals
        self._token = token
        self._model = model
        self._job = job

    def run(self) -> None:
        payload: tuple[str, Any] | None = None
        error: Exception | None = None
        try:
            with self._ui.service_context() as ctx:
                service = AIService(ctx, model=self._model)
                try:
                    payload = self._job(service)
                except HotelError as exc:
                    error = exc
        except Exception as exc:  # pragma: no cover - beklenmeyen altyapi hatasi
            log.error("ai_gorevi_coktu", error=str(exc), exc_info=True)
            error = exc

        # Ekran kapatilmis olabilir: sinyal nesnesi ekranin cocugu oldugu icin
        # C++ tarafinda silinmis olur ve emit RuntimeError firlatir. Bu, is
        # parcaciginda yakalanmazsa arka planda gurultulu bir iz birakir.
        try:
            if error is not None:
                self._signals.failed.emit(self._token, error)
            elif payload is not None:
                self._signals.finished.emit(self._token, payload[0], payload[1])
        except RuntimeError:
            log.info("ai_yaniti_ekran_kapandigi_icin_atildi", token=self._token)


@dataclass(frozen=True, slots=True)
class TaskButtonSpec:
    """Sol paneldeki hazir gorev dugmesi."""

    key: str
    label: str
    hint: str
    needs_text: bool = False


TASK_BUTTONS: tuple[TaskButtonSpec, ...] = (
    TaskButtonSpec("daily", "Gunluk Ozet", "Bugunun panel verilerini ozetler."),
    TaskButtonSpec(
        "occupancy",
        "Doluluk Analizi",
        f"Son {OCCUPANCY_WINDOW_DAYS} gunun doluluk egilimini yorumlar.",
    ),
    TaskButtonSpec(
        "pricing",
        "Fiyat Onerisi",
        f"Onumuzdeki {PRICING_WINDOW_DAYS} gun icin fiyat onerisi uretir (uygulamaz).",
    ),
    TaskButtonSpec(
        "draft",
        "Mesaj Taslagi",
        "Asagiya yazdiginiz baglamdan misafir mesaji taslagi uretir.",
        needs_text=True,
    ),
    TaskButtonSpec(
        "review",
        "Yorum Analizi",
        "Asagiya yapistirdiginiz misafir yorumunu siniflandirir.",
        needs_text=True,
    ),
    TaskButtonSpec("free", "Serbest Soru", "Girdi alanina odaklanir; sorunuzu yazip gonderin."),
)


class AICenterPage(BasePage):
    """Hazir gorevler, sohbet gecmisi ve saglayici durumu."""

    required_permission = Perm.AI_USE
    title = "Yapay Zeka Merkezi"
    icon = "\U0001f916"

    # ----------------------------------------------------------------- #
    #  Kurulum
    # ----------------------------------------------------------------- #
    def build(self) -> None:
        self._pool = QThreadPool.globalInstance()
        self._signals = _AiJobSignals(self)
        self._signals.finished.connect(self._on_job_finished)
        self._signals.failed.connect(self._on_job_failed)

        self._jobs: dict[int, _AiJob] = {}
        self._token = 0
        self._active_token: int | None = None
        #: Arayuzu kilitlemeyen isler (saglik kontrolu). Baglanti testi
        #: saniyeler surebilir; bu sirada kullanicinin gorev dugmelerini
        #: kilitlemek, ekrani acar acmaz beklemeye zorlardi.
        self._background_tokens: set[int] = set()
        self._ai_enabled = True
        self._has_messages = False
        self._follow_bottom = True

        self._build_header()
        self._build_body()
        self._build_composer()

    def _build_header(self) -> None:
        header = QHBoxLayout()
        header.addWidget(SectionTitle(t("ai.title")))
        header.addSpacing(16)

        header.addWidget(QLabel(t("ai.provider")))
        self._provider_combo = QComboBox()
        self._provider_combo.setMinimumWidth(130)
        self._provider_combo.setToolTip(
            "Istek sirasi Ayarlar > Yapay Zeka ekranindan belirlenir. "
            "Buradan secilen saglayici baglanti testinde kullanilir."
        )
        header.addWidget(self._provider_combo)

        header.addWidget(QLabel(t("ai.model")))
        self._model_combo = QComboBox()
        self._model_combo.setMinimumWidth(230)
        self._model_combo.setToolTip("Bu ekrandan gonderilen isteklerde kullanilacak model.")
        header.addWidget(self._model_combo)

        self._status_badge = StatusBadge("Kontrol edilmedi", "info")
        header.addWidget(self._status_badge)

        self._test_button = QPushButton(t("ai.test_connection"))
        self._test_button.clicked.connect(self._on_test_connection)
        header.addWidget(self._test_button)

        header.addStretch(1)
        self.root_layout.addLayout(header)

    def _build_body(self) -> None:
        body = QHBoxLayout()
        body.setSpacing(14)

        # --- Sol: hazir gorevler ---
        task_card = Card("Hazir Gorevler", self)
        self._task_buttons: dict[str, QPushButton] = {}
        for spec in TASK_BUTTONS:
            button = QPushButton(spec.label)
            button.setToolTip(spec.hint)
            button.clicked.connect(lambda _checked=False, key=spec.key: self._on_task(key))
            task_card.add_widget(button)
            self._task_buttons[spec.key] = button

        draft_label = QLabel("Taslak turu")
        draft_label.setObjectName("Muted")
        task_card.add_widget(draft_label)
        self._draft_combo = QComboBox()
        for kind in DraftKind:
            self._draft_combo.addItem(kind.label, userData=kind.value)
        self._draft_combo.setToolTip("'Mesaj Taslagi' gorevinde uretilecek metin turu.")
        task_card.add_widget(self._draft_combo)

        notice = QLabel(t("ai.verify_notice"))
        notice.setObjectName("Muted")
        notice.setWordWrap(True)
        task_card.add_widget(notice)
        task_card.body.addStretch(1)

        task_card.setMinimumWidth(220)
        task_card.setMaximumWidth(250)
        body.addWidget(task_card, 0)

        # --- Sag: sohbet ---
        chat_card = Card("Sohbet", self)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget()
        self._chat_layout = QVBoxLayout(container)
        self._chat_layout.setContentsMargins(0, 0, 6, 0)
        self._chat_layout.setSpacing(10)
        self._chat_layout.addStretch(1)
        self._scroll.setWidget(container)
        # Yeni balon eklendiginde yerlesim birkac olay dongusu sonra oturur;
        # ``rangeChanged`` tam o anda tetiklenir. Yalnizca zamanlayiciya
        # guvenmek, uzun bir yanitta listenin ortasinda kalmaya yol aciyordu.
        self._scroll.verticalScrollBar().rangeChanged.connect(self._on_scroll_range_changed)
        chat_card.add_widget(self._scroll)
        body.addWidget(chat_card, 1)

        self.root_layout.addLayout(body, 1)

    def _build_composer(self) -> None:
        self._busy_row = QHBoxLayout()
        self._busy_label = QLabel("Yanit bekleniyor...")
        self._busy_label.setObjectName("Muted")
        self._busy_bar = QProgressBar()
        # Belirsiz (indeterminate) kip: sure onceden bilinemez.
        self._busy_bar.setRange(0, 0)
        self._busy_bar.setMaximumWidth(180)
        self._cancel_button = QPushButton(t("common.cancel"))
        self._cancel_button.clicked.connect(self._on_cancel)
        self._busy_row.addWidget(self._busy_label)
        self._busy_row.addWidget(self._busy_bar)
        self._busy_row.addWidget(self._cancel_button)
        self._busy_row.addStretch(1)
        self.root_layout.addLayout(self._busy_row)

        composer = QHBoxLayout()
        self._input = QPlainTextEdit()
        self._input.setPlaceholderText(
            "Sorunuzu yazin veya bir gorev icin metni buraya yapistirin (Ctrl+Enter: gonder)"
        )
        self._input.setMaximumHeight(76)
        self._input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._send_button = QPushButton("Gonder")
        self._send_button.setObjectName("Primary")
        self._send_button.setMinimumWidth(110)
        self._send_button.clicked.connect(self._on_send)

        composer.addWidget(self._input, 1)
        composer.addWidget(self._send_button, 0)
        self.root_layout.addLayout(composer)

        # Mesgul gostergesi tum bilesenler kuruldugu icin en sona birakilir:
        # _set_busy girdi ve dugmeleri de etkiler.
        self._set_busy(False)

    # ----------------------------------------------------------------- #
    #  Veri
    # ----------------------------------------------------------------- #
    def load_data(self) -> None:
        """Saglayici/model listelerini doldurur ve baslangic durumunu kurar."""
        with self.ui.service_context(commit=False) as ctx:
            service = AIService(ctx)
            enabled = service.is_enabled
            providers = service.provider_names()
            models = service.model_options()

        self._ai_enabled = enabled

        self._provider_combo.clear()
        self._provider_combo.addItems(providers or ["-"])
        self._model_combo.clear()
        self._model_combo.addItem("Otomatik (gorev turune gore)", userData="")
        for model_id in models:
            self._model_combo.addItem(model_id, userData=model_id)

        if not enabled:
            self._show_disabled_state()
            return

        self._set_controls_enabled(True)
        self._status_badge.set_status("Kontrol ediliyor...", "info")
        self._show_welcome_state()
        self._start_job(
            "saglik",
            lambda service: ("health", service.provider_status()),
            blocking=False,
        )

    def _show_disabled_state(self) -> None:
        """Yapay zeka kapaliyken durumu ve **cozumu** gosterir."""
        self._status_badge.set_status("Kapali", "warning")
        self._set_controls_enabled(False)
        self._clear_chat()
        self._insert_empty_state(
            EmptyState(
                "Yapay zeka ozellikleri su anda kapali.",
                hint=REMEDY_AI_DISABLED,
                icon="\U0001f50c",
                parent=self,
            )
        )

    def _show_welcome_state(self) -> None:
        if self._has_messages:
            return
        self._clear_chat()
        self._insert_empty_state(
            EmptyState(
                "Soldaki hazir gorevlerden birini secin ya da sorunuzu asagiya yazin.",
                hint="Yanitlar 'AI tarafindan olusturuldu' rozetiyle isaretlenir.",
                icon="\U0001f4ac",
                parent=self,
            )
        )

    def _insert_empty_state(self, widget: QWidget) -> None:
        """Bos durumu sohbet alaninin ORTASINA yerlestirir.

        Yerlesimin sonundaki esnek boslugun (``addStretch``) katsayisi gecici
        olarak sifirlanir; aksi halde fazla yukseklik boslukla paylasilir ve
        mesaj en ustte kalip altta kocaman bir karanlik alan birakirdi.
        Katsayi ilk mesaj eklendiginde :meth:`_append` icinde geri alinir.
        """
        self._chat_layout.insertWidget(0, _expanding(widget), 1)
        self._chat_layout.setStretch(self._chat_layout.count() - 1, 0)

    def _clear_chat(self) -> None:
        """Sohbet alanini bosaltir (sondaki esnek boslugu korur).

        ``setParent(None)`` cagrisi **zorunludur**: yalnizca ``takeAt`` ile
        yerlesimden cikarilan bir bilesen ust bilesenin cocugu olmaya devam
        eder ve son geometrisinde cizilmeye devam eder - eski karsilama
        metni yeni mesajlarin uzerine binerdi. ``deleteLater`` ise ancak olay
        dongusune donuldugunde islenir, dolayisiyla tek basina yetmez.
        """
        while self._chat_layout.count() > 1:
            item = self._chat_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    # ----------------------------------------------------------------- #
    #  Gorevler
    # ----------------------------------------------------------------- #
    def _on_task(self, key: str) -> None:
        if key == "free":
            self._input.setFocus()
            return
        if not self._guard_ready():
            return

        text = self._input.toPlainText().strip()
        spec = next((s for s in TASK_BUTTONS if s.key == key), None)
        if spec is not None and spec.needs_text and not text:
            show_toast(
                self,
                "Once asagidaki alana metni yazin, sonra bu gorevi calistirin.",
                ToastLevel.WARNING,
            )
            self._input.setFocus()
            return

        today = utcnow().date()
        if key == "daily":
            self._add_user_message("Gunluk ozet istendi.")
            self._start_job("gunluk", lambda s: ("text", s.daily_summary(today)))
        elif key == "occupancy":
            window = default_occupancy_window(today)
            self._add_user_message(f"Doluluk analizi istendi ({OCCUPANCY_WINDOW_DAYS} gun).")
            self._start_job("doluluk", lambda s: ("text", s.occupancy_analysis(window)))
        elif key == "pricing":
            window = default_pricing_window(today)
            self._add_user_message(f"Fiyat onerisi istendi ({PRICING_WINDOW_DAYS} gun).")
            self._start_job("fiyat", lambda s: ("pricing", s.pricing_suggestion(window)))
        elif key == "draft":
            kind = DraftKind(self._draft_combo.currentData() or DraftKind.RESERVATION_CONFIRMATION)
            self._add_user_message(f"{kind.label} taslagi istendi:\n{text}")
            self._input.clear()
            self._start_job("taslak", lambda s: ("draft", s.draft_message(kind, {"durum": text})))
        elif key == "review":
            self._add_user_message(f"Yorum analizi istendi:\n{text}")
            self._input.clear()
            self._start_job("yorum", lambda s: ("review", s.classify_review(text)))

    def _on_send(self) -> None:
        if not self._guard_ready():
            return
        question = self._input.toPlainText().strip()
        if not question:
            show_toast(self, "Once bir soru yazin.", ToastLevel.WARNING)
            return
        self._add_user_message(question)
        self._input.clear()
        self._start_job("soru", lambda s: ("text", s.ask(question)))

    def _on_test_connection(self) -> None:
        if not self._ai_enabled:
            show_toast(self, "Yapay zeka kapali. " + REMEDY_AI_DISABLED, ToastLevel.WARNING)
            return
        self._status_badge.set_status("Kontrol ediliyor...", "info")
        self._start_job(
            "saglik",
            lambda s: ("health", s.provider_status()),
            blocking=False,
        )

    def _guard_ready(self) -> bool:
        """Yeni bir istek baslatilabilir mi?"""
        if not self._ai_enabled:
            show_toast(self, "Yapay zeka kapali. " + REMEDY_AI_DISABLED, ToastLevel.WARNING)
            return False
        if self._active_token is not None:
            show_toast(self, "Bir istek zaten calisiyor.", ToastLevel.INFO)
            return False
        return True

    # ----------------------------------------------------------------- #
    #  Is parcacigi yasam dongusu
    # ----------------------------------------------------------------- #
    def _start_job(
        self,
        name: str,
        job: Callable[[AIService], tuple[str, Any]],
        *,
        blocking: bool = True,
    ) -> None:
        """Cagriyi arka planda baslatir.

        ``blocking=False`` yalnizca saglik kontrolu icindir: ekran acilir
        acilmaz baslayan bu kontrol saniyeler surebilir ve o sure boyunca
        gorev dugmelerini kilitlemek kullaniciyi bosuna bekletirdi.
        """
        self._token += 1
        token = self._token
        if blocking:
            self._active_token = token
            self._set_busy(True, name)
        else:
            self._background_tokens.add(token)

        runnable = _AiJob(
            self.ui,
            self._signals,
            token,
            self._model_combo.currentData() or "",
            job,
        )
        self._jobs[token] = runnable
        self._pool.start(runnable)

    def _on_job_finished(self, token: int, kind: str, payload: Any) -> None:
        self._jobs.pop(token, None)
        if token in self._background_tokens:
            self._background_tokens.discard(token)
            self._apply_health(payload)
            return
        if token != self._active_token:
            # Iptal edilmis ya da eskimis istek: sonuc yok sayilir.
            log.info("ai_yaniti_yok_sayildi", token=token)
            return
        self._active_token = None
        self._set_busy(False)

        if kind == "text":
            self._add_result_message(payload)
        elif kind == "draft":
            self._add_draft_message(payload)
        elif kind == "pricing":
            self._add_pricing_message(payload)
        elif kind == "review":
            self._add_review_message(payload)

    def _on_job_failed(self, token: int, error: Exception) -> None:
        self._jobs.pop(token, None)
        if token in self._background_tokens:
            # Saglik kontrolu basarisiz: yalnizca rozet guncellenir, kullaniciya
            # kesintiye ugratan bir pencere gosterilmez.
            self._background_tokens.discard(token)
            self._status_badge.set_status(t("ai.connection_failed"), "danger")
            log.info("ai_saglik_kontrolu_basarisiz", error=str(error))
            return
        if token != self._active_token:
            return
        self._active_token = None
        self._set_busy(False)

        if isinstance(error, HotelError):
            remedy = error.context.get("cozum") or getattr(error, "remedy", None)
            self._add_error_message(error.user_message, str(remedy) if remedy else "")
            self._status_badge.set_status(t("ai.connection_failed"), "danger")
        else:
            self._add_error_message("Beklenmeyen bir hata olustu.", "")
        show_error(self, error)

    def _on_cancel(self) -> None:
        """Bekleyen istegin sonucunu yok sayar ve arayuzu serbest birakir.

        Saglayiciya gonderilmis istek gercekten durdurulamaz; model uretmeye
        devam eder ve kullanim kaydi yazilir. Kullaniciya bu durustce soylenir.
        """
        if self._active_token is None:
            return
        log.info("ai_istegi_iptal_edildi", token=self._active_token)
        self._active_token = None
        self._set_busy(False)
        self._add_note_message(
            "Istek iptal edildi. Yanit gelse bile gosterilmeyecek; "
            "saglayiciya gonderilmis istek durdurulamadigi icin kullanim kaydi yine olusur."
        )

    def _set_busy(self, busy: bool, name: str = "") -> None:
        self._busy_label.setVisible(busy)
        self._busy_bar.setVisible(busy)
        self._cancel_button.setVisible(busy)
        if busy:
            self._busy_label.setText(
                f"Yanit bekleniyor... ({name})" if name else "Yanit bekleniyor..."
            )
        self._set_controls_enabled(not busy and self._ai_enabled)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for button in self._task_buttons.values():
            button.setEnabled(enabled)
        self._send_button.setEnabled(enabled)
        self._input.setEnabled(enabled)
        self._test_button.setEnabled(enabled)
        self._draft_combo.setEnabled(enabled)
        self._model_combo.setEnabled(enabled)

    def _apply_health(self, report: dict[str, Any]) -> None:
        """Saglik raporunu durum rozetine yansitir."""
        if not report:
            self._status_badge.set_status("Bilinmiyor", "warning")
            return
        healthy = [name for name, status in report.items() if status.ok]
        if healthy:
            self._status_badge.set_status(f"{t('ai.connection_ok')} ({healthy[0]})", "success")
            return

        first = next(iter(report.values()))
        self._status_badge.set_status(t("ai.connection_failed"), "danger")
        if not self._has_messages:
            self._clear_chat()
            self._insert_empty_state(
                EmptyState(
                    "Yapay zeka saglayicisina ulasilamiyor.",
                    hint=(first.message or REMEDY_AI_DISABLED),
                    icon="⚠",
                    parent=self,
                )
            )

    # ----------------------------------------------------------------- #
    #  Sohbet balonlari
    # ----------------------------------------------------------------- #
    def _append(self, widget: QWidget, *, role: str = "assistant") -> None:
        """Balonu sohbete ekler ve en alta kaydirir.

        Kullanici mesajlari soldan bosluk birakilarak, asistan mesajlari
        sagdan bosluk birakilarak yerlestirilir. Bu **renksiz** ayrim, renk
        korlugu olan kullanicilar icin de calisir ve rozet/baslik ile birlikte
        kimin konustugunu bir bakista gosterir.
        """
        if not self._has_messages:
            self._clear_chat()
            self._has_messages = True

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setSpacing(0)
        if role in {"user", "note"}:
            layout.setContentsMargins(96, 0, 0, 0)
        else:
            layout.setContentsMargins(0, 0, 64, 0)
        layout.addWidget(widget)

        self._follow_bottom = True
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, row)
        # Bos durum icin sifirlanan esnek bosluk geri alinir: balonlar
        # yukaridan asagiya siralanmali, ortalanmamalidir.
        self._chat_layout.setStretch(self._chat_layout.count() - 1, 1)
        # Yerlesim guncellendikten SONRA en alta kaydir; ayni dongude
        # yapilirsa maximum() henuz eski degerdedir.
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_scroll_range_changed(self, _minimum: int, maximum: int) -> None:
        if self._follow_bottom:
            self._scroll.verticalScrollBar().setValue(maximum)

    def _add_user_message(self, text: str) -> None:
        self._append(_bubble(self, role="user", title="Siz", body=text), role="user")

    def _add_note_message(self, text: str) -> None:
        self._append(_bubble(self, role="note", title="Bilgi", body=text), role="note")

    def _add_error_message(self, message: str, remedy: str) -> None:
        card = _bubble(self, role="error", title="Hata", body=message)
        if remedy:
            hint = QLabel(remedy)
            hint.setObjectName("Muted")
            hint.setWordWrap(True)
            card.layout().addWidget(hint)
        self._append(card)

    def _add_result_message(self, result: AIResult) -> None:
        card = self._assistant_card(result, result.content)
        self._append(_finish_card(card, result))

    def _add_draft_message(self, draft: AIDraft) -> None:
        card = self._assistant_card(draft.result, draft.body)
        note = QLabel(
            "Bu taslak gonderilmedi. Metni kontrol edip kopyalayarak kullanabilirsiniz. — "
            + AI_GENERATED_MARKER
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        card.layout().addWidget(note)
        self._append(_finish_card(card, draft.result))

    def _add_review_message(self, review: ReviewClassification) -> None:
        card = self._assistant_card(review.result, review.summary or review.result.content)

        badges = QHBoxLayout()
        badges.setSpacing(8)
        badges.addWidget(
            StatusBadge(f"Duygu: {review.sentiment}", review.sentiment_level, parent=card)
        )
        badges.addWidget(
            StatusBadge(f"Puan: {format_number(review.score, decimals=2)}", "info", parent=card)
        )
        if review.is_urgent:
            badges.addWidget(StatusBadge("Acil mudahale", "danger", parent=card))
        for category in review.categories[:6]:
            badges.addWidget(StatusBadge(category, "info", parent=card))
        badges.addStretch(1)
        card.layout().addLayout(badges)
        self._append(_finish_card(card, review.result))

    def _add_pricing_message(self, suggestion: PricingSuggestion) -> None:
        """Fiyat onerisini gosterir. **Fiyati degistiren dugme YOKTUR.**"""
        card = self._assistant_card(suggestion.result, suggestion.summary)

        warning = QLabel(PRICING_ADVISORY_NOTE)
        warning.setObjectName("BadgeWarning")
        warning.setWordWrap(True)
        card.layout().addWidget(warning)

        if suggestion.items:
            grid = QGridLayout()
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(4)
            for column, header in enumerate(("Tarih", "Oda Tipi", "Mevcut", "Onerilen", "Gerekce")):
                label = QLabel(header)
                label.setObjectName("CardTitle")
                grid.addWidget(label, 0, column)

            for row, item in enumerate(suggestion.items[:MAX_SUGGESTION_ROWS], start=1):
                change = item.change_percent
                suffix = f"  ({change:+.1f}%)".replace(".", ",") if change is not None else ""
                cells = (
                    item.day.strftime("%d.%m.%Y") if item.day else "-",
                    item.room_type,
                    item.current_rate.format() if item.current_rate else "-",
                    (item.suggested_rate.format() if item.suggested_rate else "-") + suffix,
                    item.rationale,
                )
                for column, text in enumerate(cells):
                    cell = QLabel(text)
                    cell.setWordWrap(column == 4)
                    grid.addWidget(cell, row, column)
            grid.setColumnStretch(4, 1)
            card.layout().addLayout(grid)

        self._append(_finish_card(card, suggestion.result))

    def _assistant_card(self, result: AIResult, body: str) -> QFrame:
        """Yapay zeka yaniti balonu: rozet, icerik ve akil yurutme.

        Olcum satiri (model, sure, jeton, maliyet) burada **eklenmez**;
        gorev turune ozel eklentiler (fiyat uyarisi, oneri tablosu, rozetler)
        araya girecegi icin en sona :func:`_finish_card` ile eklenir. Aksi
        halde maliyet satiri oneri tablosunun ustunde kalir ve balonun
        "sonu" belirsizlesir.
        """
        return _bubble(self, role="assistant", title="Yapay Zeka", body=body, result=result)


# ==========================================================================
#  Yerlesim yardimcilari
# ==========================================================================
def _expanding(widget: QWidget) -> QWidget:
    """Bos durum bilesenini kalan dikey alanin tamamina yayar.

    Varsayilan ``Preferred`` politikasiyla eklendiginde bos durum sohbet
    alaninin en ustune sikisiyor ve altta kocaman bir bosluk kaliyordu.
    """
    widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
    return widget


# ==========================================================================
#  Balon yapisi
# ==========================================================================
_ROLE_TITLES: dict[str, str] = {
    "user": "Siz",
    "assistant": "Yapay Zeka",
    "note": "Bilgi",
    "error": "Hata",
}


def _bubble(
    parent: QWidget,
    *,
    role: str,
    title: str,
    body: str,
    result: AIResult | None = None,
) -> QFrame:
    """Tek bir sohbet balonu olusturur.

    Yapay zeka yanitlarinda :class:`~app.ui.widgets.common.AiBadge` **her
    zaman** gosterilir - kullanici hangi metnin model ciktisi oldugunu
    ayirt edebilmelidir. Dusunme (reasoning) metni varsa katlanabilir bir
    bolumde ve **varsayilan olarak kapali** sunulur: akil yurutme kullaniciya
    yanit degildir, hata ayiklama malzemesidir.
    """
    card = QFrame(parent)
    card.setObjectName("Card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 10, 14, 10)
    layout.setSpacing(6)

    header = QHBoxLayout()
    header.setSpacing(8)
    name = QLabel(title or _ROLE_TITLES.get(role, role))
    name.setObjectName("CardTitle")
    header.addWidget(name)
    if role == "assistant":
        header.addWidget(AiBadge(card))
    if role == "error":
        header.addWidget(StatusBadge("Basarisiz", "danger", parent=card))
    header.addStretch(1)
    stamp = QLabel(format_datetime(utcnow()))
    stamp.setObjectName("Muted")
    header.addWidget(stamp)
    layout.addLayout(header)

    content = QLabel(body or "-")
    content.setWordWrap(True)
    content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if role == "user":
        content.setObjectName("Muted")
    layout.addWidget(content)

    if result is not None and result.has_reasoning:
        layout.addWidget(_reasoning_section(card, result.reasoning))

    return card


def _finish_card(card: QFrame, result: AIResult) -> QFrame:
    """Balonun sonuna olcum satirini ekler ve balonu dondurur."""
    card.layout().addWidget(_meta_label(card, result))
    return card


def _reasoning_section(parent: QWidget, reasoning: str) -> QWidget:
    """Katlanabilir "Modelin akil yurutmesi" bolumu - varsayilan KAPALI."""
    holder = QWidget(parent)
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)

    toggle = QToolButton(holder)
    toggle.setText("Modelin akil yurutmesi")
    toggle.setCheckable(True)
    toggle.setChecked(False)
    toggle.setArrowType(Qt.ArrowType.RightArrow)
    toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    toggle.setToolTip(
        "Modelin cevaba nasil ulastigina dair ic metin. Kullaniciya sunulan yanit degildir."
    )

    text = QLabel(reasoning, holder)
    text.setObjectName("Muted")
    text.setWordWrap(True)
    text.setVisible(False)
    text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    def _toggled(checked: bool) -> None:
        text.setVisible(checked)
        toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

    toggle.toggled.connect(_toggled)

    layout.addWidget(toggle)
    layout.addWidget(text)
    return holder


def _meta_label(parent: QWidget, result: AIResult) -> QLabel:
    """Model adi, sure, jeton ve tahmini maliyet satiri."""
    parts = [
        result.model or "model belirtilmedi",
        result.duration_text,
        f"{format_number(result.total_tokens)} jeton",
        f"maliyet: {result.cost_text}",
    ]
    if result.reasoning_tokens:
        parts.insert(3, f"{format_number(result.reasoning_tokens)} dusunme jetonu")
    if result.used_fallback:
        parts.append("yedek saglayici kullanildi")
    label = QLabel("  •  ".join(parts), parent)
    label.setObjectName("Muted")
    label.setWordWrap(True)
    return label


def default_occupancy_window(today: date | None = None) -> DateRange:
    """Doluluk analizinin varsayilan penceresi (bugun dahil)."""
    reference = today or utcnow().date()
    return DateRange(reference - timedelta(days=OCCUPANCY_WINDOW_DAYS), reference + timedelta(1))


def default_pricing_window(today: date | None = None) -> DateRange:
    """Fiyat onerisinin varsayilan penceresi."""
    reference = today or utcnow().date()
    return DateRange(reference, reference + timedelta(days=PRICING_WINDOW_DAYS))


__all__ = [
    "OCCUPANCY_WINDOW_DAYS",
    "PRICING_WINDOW_DAYS",
    "TASK_BUTTONS",
    "AICenterPage",
    "TaskButtonSpec",
    "default_occupancy_window",
    "default_pricing_window",
]
