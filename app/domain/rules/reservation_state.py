"""Rezervasyon durum makinesi.

Gecerli gecisler :data:`~app.domain.enums.RESERVATION_TRANSITIONS` icinde
tanimlidir. Bu modul, o tabloyu kullanarak gecisleri dogrular ve arayuze
"hangi dugmeler etkin olmali" bilgisini saglar.

Neden bir durum makinesi?
-------------------------
Durum gecislerini serbest birakmak, gercek isletmede veri bozulmasina yol
acar: iptal edilmis bir rezervasyona check-in yapilmasi, cikis yapmis bir
misafirin yeniden "otelde" gorunmesi gibi. Gecisleri tek yerde tanimlamak,
bu hatalari kaynagında engeller.
"""

from __future__ import annotations

from app.core.exceptions import InvalidStateTransitionError
from app.domain.enums import (
    RESERVATION_TRANSITIONS,
    TERMINAL_RESERVATION_STATUSES,
    ReservationStatus,
)


def allowed_transitions(current: ReservationStatus) -> frozenset[ReservationStatus]:
    """Mevcut durumdan gidilebilecek durumlar.

    >>> sorted(s.value for s in allowed_transitions(ReservationStatus.CHECKED_IN))
    ['checked_out']
    >>> allowed_transitions(ReservationStatus.CANCELLED)
    frozenset()
    """
    return RESERVATION_TRANSITIONS.get(current, frozenset())


def can_transition(current: ReservationStatus, target: ReservationStatus) -> bool:
    """Gecis gecerli mi?

    >>> can_transition(ReservationStatus.CONFIRMED, ReservationStatus.CHECKED_IN)
    True
    >>> can_transition(ReservationStatus.CANCELLED, ReservationStatus.CHECKED_IN)
    False
    >>> can_transition(ReservationStatus.CONFIRMED, ReservationStatus.CONFIRMED)
    True
    """
    if current is target:
        return True  # ayni duruma "gecis" islemsizdir
    return target in allowed_transitions(current)


def assert_transition_allowed(current: ReservationStatus, target: ReservationStatus) -> None:
    """Gecis gecersizse anlamli bir hata firlatir."""
    if can_transition(current, target):
        return

    options = allowed_transitions(current)
    if not options:
        detail = f"'{current.label}' durumu kapalidir; baska bir duruma gecilemez."
    else:
        detail = "Gidilebilecek durumlar: " + ", ".join(sorted(s.label for s in options))

    raise InvalidStateTransitionError(
        f"'{current.label}' durumundaki bir rezervasyon '{target.label}' yapilamaz. {detail}",
        detail=f"{current.value} -> {target.value} gecisine izin verilmiyor.",
        context={"current": current.value, "target": target.value},
    )


def is_terminal(status: ReservationStatus) -> bool:
    """Rezervasyon kapanmis mi (artik degistirilemez)?

    >>> is_terminal(ReservationStatus.CHECKED_OUT)
    True
    >>> is_terminal(ReservationStatus.CONFIRMED)
    False
    """
    return status in TERMINAL_RESERVATION_STATUSES


def is_modifiable(status: ReservationStatus) -> bool:
    """Rezervasyonun tarih/oda bilgileri degistirilebilir mi?

    Giris yapilmis rezervasyonlarda tarih degisikligi ancak uzatma seklinde
    yapilir; bu yuzden "serbestce degistirilebilir" degildir.
    """
    return status in {
        ReservationStatus.DRAFT,
        ReservationStatus.TENTATIVE,
        ReservationStatus.CONFIRMED,
        ReservationStatus.WAITLIST,
    }


def is_cancellable(status: ReservationStatus) -> bool:
    """Rezervasyon iptal edilebilir mi?"""
    return ReservationStatus.CANCELLED in allowed_transitions(status)


def is_checkin_allowed(status: ReservationStatus) -> bool:
    """Check-in yapilabilir mi?"""
    return ReservationStatus.CHECKED_IN in allowed_transitions(status)


def is_checkout_allowed(status: ReservationStatus) -> bool:
    """Check-out yapilabilir mi?"""
    return ReservationStatus.CHECKED_OUT in allowed_transitions(status)


def available_actions(status: ReservationStatus) -> dict[str, bool]:
    """Arayuzun dugme etkinliklerini belirlemesi icin ozet.

    >>> a = available_actions(ReservationStatus.CONFIRMED)
    >>> a["check_in"], a["cancel"], a["check_out"]
    (True, True, False)
    """
    return {
        "modify": is_modifiable(status),
        "cancel": is_cancellable(status),
        "check_in": is_checkin_allowed(status),
        "check_out": is_checkout_allowed(status),
        "mark_no_show": ReservationStatus.NO_SHOW in allowed_transitions(status),
        "confirm": ReservationStatus.CONFIRMED in allowed_transitions(status),
    }


__all__ = [
    "allowed_transitions",
    "assert_transition_allowed",
    "available_actions",
    "can_transition",
    "is_cancellable",
    "is_checkin_allowed",
    "is_checkout_allowed",
    "is_modifiable",
    "is_terminal",
]
