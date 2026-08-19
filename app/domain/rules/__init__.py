"""Is kurallari - veritabanindan ve arayuzden bagimsiz saf fonksiyonlar.

Bu paketteki fonksiyonlar SQLAlchemy oturumu almaz; kendilerine verilen sade
veri yapilari uzerinde calisir. Sorgular :mod:`app.infrastructure.db.repositories`
katmaninda, iliskilendirme ise :mod:`app.application.services` katmanindadir.
Boylece kurallar veritabani olmadan, milisaniyeler icinde test edilebilir.
"""

from __future__ import annotations

from app.domain.rules.availability import (
    Booking,
    OccupancyStats,
    RoomBlock,
    check_availability,
    compute_occupancy,
    find_conflicting_bookings,
    free_gaps,
)
from app.domain.rules.pricing import (
    NightlyRate,
    PriceBreakdown,
    RateRule,
    calculate_cancellation_fee,
    calculate_stay_price,
)
from app.domain.rules.reservation_state import (
    allowed_transitions,
    assert_transition_allowed,
    can_transition,
)

__all__ = [
    "Booking",
    "NightlyRate",
    "OccupancyStats",
    "PriceBreakdown",
    "RateRule",
    "RoomBlock",
    "allowed_transitions",
    "assert_transition_allowed",
    "calculate_cancellation_fee",
    "calculate_stay_price",
    "can_transition",
    "check_availability",
    "compute_occupancy",
    "find_conflicting_bookings",
    "free_gaps",
]
