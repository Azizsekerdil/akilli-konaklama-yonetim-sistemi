"""Yapilandirilmis loglama ve hassas veri maskeleme.

Bu modulun iki gorevi vardir:

1. **Yapilandirilmis log** - ``structlog`` ile hem insan okunur (gelistirme)
   hem JSON (uretim) cikti; dosyaya donen (rotating) yazim.
2. **Maskeleme** - API anahtari, parola, e-posta, telefon, TCKN, kart numarasi
   gibi veriler loga **duz metin olarak yazilmaz**. Bu, hem KVKK hem de
   ``docs/SECURITY_REVIEW.md`` gerekliliklerindendir.

.. note::
   Modul adi bilerek ``log`` secilmistir (``logging`` degil): bir paket icinde
   ``logging.py`` adli dosya, bazi arac zincirlerinde (doctest, PyInstaller,
   betik olarak calistirma) standart kutuphanenin ``logging`` modulunu
   golgeleyip ``ModuleNotFoundError: No module named 'logging.handlers'``
   hatasina yol acar. Ayni gerekce ile sir yonetimi modulu
   :mod:`app.core.secret_store` adini tasir (stdlib ``secrets`` ile cakismasin).

Kullanim::

    from app.core.log import get_logger, setup_logging

    setup_logging()                      # uygulama girisinde bir kez
    log = get_logger(__name__)
    log.info("rezervasyon_olusturuldu", reservation_id=42, guest_email="a@b.com")
    # -> guest_email='a***@b.com' seklinde maskelenir
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any, Final

import structlog

from app.core.secret_store import looks_like_secret_key

# --------------------------------------------------------------------------
#  Maskeleme desenleri
# --------------------------------------------------------------------------
#: ``sk-...``, ``nvapi-...`` gibi bilinen anahtar onekleri.
_API_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(sk-|nvapi-|xai-|gsk_|hf_|ghp_|gho_|github_pat_)[A-Za-z0-9_\-]{8,}",
)

#: ``Authorization: Bearer <token>`` basliklari.
_BEARER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(bearer|token|api[_-]?key)\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.]{8,})",
)

#: E-posta adresleri.
_EMAIL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b([A-Za-z0-9._%+\-])([A-Za-z0-9._%+\-]*)@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b",
)

#: 11 haneli T.C. kimlik numarasi benzeri diziler.
_TCKN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\b[1-9][0-9]{10}\b")

#: 13-19 haneli kart numarasi benzeri diziler (bosluk/tire ayirici olabilir).
_CARD_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:\d[ \-]?){12,18}\d\b",
)

#: Turkiye telefon numarasi benzeri diziler.
_PHONE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:\+90|0)?[ \-]?5\d{2}[ \-]?\d{3}[ \-]?\d{2}[ \-]?\d{2}\b",
)

MASK: Final[str] = "***MASKELENDI***"

#: **Onek tasimayan** sir atamalari, or. ``HOTEL_SECRET_KEY=uzun-rastgele-deger``.
#:
#: Guvenlik incelemesi bulgusu HTL-H1 (ikinci yarisi): eski maskeleyici
#: yalnizca (a) ``sk-``/``nvapi-`` gibi **bilinen onekli** anahtarlari ve
#: (b) sabit bir ad listesini (``bearer|token|api_key``) taniyordu. Oturum
#: imzalama anahtari (``HOTEL_SECRET_KEY``) ve alan sifreleme anahtari
#: (``HOTEL_FIELD_ENCRYPTION_KEY``) onek tasimayan uzun rastgele dizgelerdir
#: ve hicbir desene uymadigi icin **maskelenmeden** gecerdi.
#:
#: Yeni kural: ad *sir-benzeri* ise (``secret``, ``password``, ``passwd``,
#: ``pwd``, ``token``, ``api_key``, ``credential``, ``private_key``,
#: ``...._key``) deger, oneginden bagimsiz olarak maskelenir. Bir ``.env``
#: satirinda, bir JSON alaninda ve bir komut ciktisinda ayni sekilde calisir.
_SECRET_ASSIGNMENT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?im)"
    r"(?P<name>[A-Za-z0-9_.\-]*"
    r"(?:secret|password|passwd|pwd|api[_-]?key|apikey|credential|token|private_key|_key)"
    r"[A-Za-z0-9_.\-]*)"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<quote>['\"]?)"
    r"(?P<value>[^\s'\",;]{4,})"
    r"(?P=quote)",
)

#: Deger olarak da maskelenmesi gereken alan adlari (anahtar bazli maskeleme).
_PII_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "national_id",
        "tckn",
        "tc_kimlik_no",
        "passport_no",
        "passport_number",
        "id_number",
        "card_number",
        "iban",
        "cvv",
        "cvc",
    }
)


def _mask_email(match: re.Match[str]) -> str:
    first, _rest, domain = match.groups()
    return f"{first}***@{domain}"


def _mask_assignment(match: re.Match[str]) -> str:
    return f"{match.group('name')}{match.group('sep')}{MASK}"


def mask_text(value: str) -> str:
    """Serbest metindeki hassas kaliplari maskeler.

    >>> mask_text("anahtarim sk-abcdef1234567890 burada")
    'anahtarim ***MASKELENDI*** burada'
    >>> mask_text("misafir e-postasi ahmet@ornek.com")
    'misafir e-postasi a***@ornek.com'
    >>> mask_text("HOTEL_SECRET_KEY=ORNEK-DEGER-GERCEK-DEGIL")
    'HOTEL_SECRET_KEY=***MASKELENDI***'
    """
    if not value:
        return value
    masked = _API_KEY_PATTERN.sub(MASK, value)
    # Onek tasimayan sir atamalari (HOTEL_SECRET_KEY=..., db_password: ...)
    masked = _SECRET_ASSIGNMENT_PATTERN.sub(_mask_assignment, masked)
    masked = _BEARER_PATTERN.sub(lambda m: f"{m.group(1)}: {MASK}", masked)
    masked = _EMAIL_PATTERN.sub(_mask_email, masked)
    masked = _CARD_PATTERN.sub(MASK, masked)
    masked = _TCKN_PATTERN.sub(MASK, masked)
    masked = _PHONE_PATTERN.sub(MASK, masked)
    return masked


def mask_value(key: str, value: Any, *, _depth: int = 0) -> Any:
    """Bir anahtar/deger ciftini gerektiginde maskeler.

    Anahtar adi hassassa deger tumuyle maskelenir; degilse metin icerigi
    desen bazli taranir. Ic ice sozluk ve listeler ozyinelemeli islenir.
    """
    if _depth > 6:  # asiri derin yapilarda dur
        return value

    normalized = key.lower().replace("-", "_")
    if looks_like_secret_key(key) or normalized in _PII_FIELD_NAMES:
        return MASK

    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, Mapping):
        return {k: mask_value(str(k), v, _depth=_depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        items = [mask_value(key, v, _depth=_depth + 1) for v in value]
        return type(value)(items) if not isinstance(value, set) else set(items)
    return value


def masking_processor(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog islemcisi: her log kaydini maskeleme suzgecinden gecirir."""
    for key in list(event_dict.keys()):
        event_dict[key] = mask_value(str(key), event_dict[key])
    return event_dict


def _add_app_context(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Her kayda uygulama surumunu ekler."""
    from app import __version__

    event_dict.setdefault("app_version", __version__)
    return event_dict


# --------------------------------------------------------------------------
#  Kurulum
# --------------------------------------------------------------------------
_configured = False


def _stderr_is_tty() -> bool:
    """``sys.stderr`` renkli cikti destekliyor mu?

    .. warning::
       ``sys.stderr.isatty()`` dogrudan cagrilamaz. PyInstaller ile
       ``console=False`` olarak paketlenmis bir uygulamada **``sys.stderr``
       ``None``'dir**; dogrudan cagri ``AttributeError: 'NoneType' object has
       no attribute 'isatty'`` verir ve uygulama daha acilmadan coker.
       Bu hata yalnizca paketlenmis surumde ortaya cikar - gelistirme
       ortaminda hicbir belirti vermez.
    """
    stream = sys.stderr
    if stream is None:
        return False
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):  # pragma: no cover - kapali akis
        return False


def setup_logging(
    *,
    level: str | None = None,
    json_format: bool | None = None,
    log_to_file: bool = True,
    force: bool = False,
) -> None:
    """Loglamayi kurar. Birden fazla cagrilmasi guvenlidir.

    Parameters
    ----------
    level:
        Ayarlardaki degeri gecersiz kilar (or. testlerde ``"WARNING"``).
    json_format:
        ``True`` ise JSON, ``False`` ise renkli konsol ciktisi.
    log_to_file:
        Dosyaya yazmayi kapatmak icin ``False`` (testler icin faydali).
    force:
        Daha once kurulmus olsa bile yeniden kurar.
    """
    global _configured
    if _configured and not force:
        return

    # Ayarlari tembel yukluyoruz: loglama kurulurken config import zinciri
    # olusmasin diye.
    from app.core.config import get_settings

    settings = get_settings()
    effective_level = (level or settings.logging.level).upper()
    effective_json = settings.logging.json_format if json_format is None else json_format

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(effective_level)

    # ---- Konsol ----
    # Paketlenmis pencereli uygulamada (console=False) sys.stderr None'dir;
    # StreamHandler(None) da varsayilan olarak sys.stderr'a yazmaya calisir
    # ve ilk log kaydinda coker. Bu yuzden konsol yalnizca gercekten varsa
    # eklenir - loglar her durumda dosyaya yazilmaya devam eder.
    console_handler: logging.Handler | None = None
    if sys.stderr is not None:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(effective_level)
        root.addHandler(console_handler)

    # ---- Dosya (donen) ----
    if log_to_file:
        try:
            log_dir = settings.logging.directory
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_dir / "hotel.log",
                maxBytes=settings.logging.max_bytes,
                backupCount=settings.logging.backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(effective_level)
            root.addHandler(file_handler)

            error_handler = logging.handlers.RotatingFileHandler(
                log_dir / "error.log",
                maxBytes=settings.logging.max_bytes,
                backupCount=settings.logging.backup_count,
                encoding="utf-8",
            )
            error_handler.setLevel(logging.ERROR)
            root.addHandler(error_handler)
        except OSError as exc:  # pragma: no cover - disk/izin sorunu
            # Log dosyasi acilamiyorsa uygulama calismaya devam etmeli.
            if console_handler is not None:
                console_handler.handle(
                    logging.LogRecord(
                        name="app.core.log",
                        level=logging.WARNING,
                        pathname=__file__,
                        lineno=0,
                        msg=f"Log dosyasi acilamadi, yalnizca konsola yazilacak: {exc}",
                        args=(),
                        exc_info=None,
                    )
                )

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        _add_app_context,
        masking_processor,  # <-- maskeleme her zaman son islemcilerden once
    ]

    renderer: Any
    if effective_json:
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)
        shared_processors.append(structlog.processors.format_exc_info)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=_stderr_is_tty())
        shared_processors.append(structlog.processors.format_exc_info)

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )
    for handler in root.handlers:
        handler.setFormatter(formatter)

    # Gurultulu ucuncu parti loglarini kis.
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # SQL echo ayari SQLAlchemy'nin kendi bayragiyla yonetilir.
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.database.echo else logging.WARNING
    )

    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Yapilandirilmis bir logger dondurur.

    Loglama henuz kurulmadiysa otomatik kurar; boylece modul seviyesinde
    ``log = get_logger(__name__)`` yazmak guvenlidir.
    """
    if not _configured:
        try:
            setup_logging()
        except Exception:  # pragma: no cover
            # Ayarlar okunamasa bile loglama calismali.
            logging.basicConfig(level=logging.INFO)
    return structlog.get_logger(name)


def bind_context(**kwargs: Any) -> None:
    """Gecerli baglama (thread/task) kalici log alanlari ekler.

    Ornek: giris yapan kullanicinin kimligini tum sonraki loglara eklemek::

        bind_context(user_id=user.id, username=user.username)
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Baglam alanlarini temizler (or. cikis yapildiginda)."""
    structlog.contextvars.clear_contextvars()


__all__ = [
    "MASK",
    "bind_context",
    "clear_context",
    "get_logger",
    "mask_text",
    "mask_value",
    "masking_processor",
    "setup_logging",
]
