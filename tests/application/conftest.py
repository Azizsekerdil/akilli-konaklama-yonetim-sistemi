"""Servis katmani testleri icin ortak fiksturler."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session

from app.infrastructure.db.base import utcnow
from app.infrastructure.db.models import Property, RatePlan, Room, RoomType
from app.infrastructure.db.models.guests import Guest


@pytest.fixture
def property_with_rooms(
    secured_session: Session,
    sample_property: Property,
    sample_room_type: RoomType,
    sample_rooms: list[Room],
    sample_rate_plan: RatePlan,
) -> Property:
    """Oda, oda tipi ve fiyat plani hazir bir tesis."""
    return sample_property


@pytest.fixture
def guest(secured_session: Session, sample_guest: Guest) -> Guest:
    return sample_guest


@pytest.fixture
def second_guest(secured_session: Session) -> Guest:
    """Ikinci test misafiri (uydurma)."""
    other = Guest(
        first_name="Kerem",
        last_name="Aksoy",
        email="kerem.aksoy@ornek-test.local",
        phone="+90 5XX XXX XX 02",
    )
    secured_session.add(other)
    secured_session.commit()
    return other


@pytest.fixture
def next_week() -> date:
    """Bugunden 7 gun sonrasi - gecmis tarih dogrulamalarina takilmamak icin.

    ``date.today()`` yerel saat dilimine gore hesaplanir; UTC+3'te gece
    yarisindan sonra sunucu ile bir gun kayabilir. Kayitlarin tamami UTC
    oldugundan gun sinirini da UTC'den turetiyoruz.
    """
    return utcnow().date() + timedelta(days=7)
