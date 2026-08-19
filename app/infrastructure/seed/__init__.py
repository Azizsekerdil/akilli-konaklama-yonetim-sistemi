"""Baslangic verisi: referans tanimlar ve demo veri ureteci.

Iki farkli sey ayni pakette ama **bilincli olarak ayri modullerde** durur:

``reference_data``
    Gercek bir kurulumda da olusturulan taban tanimlar (oda ozellikleri,
    ornek vergi oranlari, ek hizmetler, departmanlar). Idempotenttir ve demo
    temizlendiginde **silinmez**.

``demo_data``
    Yalnizca tanitim/deneme icin uretilen, tamamen uydurma veri kumesi. Tum
    kayitlar demo isaretlidir ve
    :func:`~app.infrastructure.seed.demo_data.clear_demo_data` ile tek
    hamlede geri alinabilir.

Ayrimin nedeni pratiktir: isletme demo verisini attiginda oda ozellikleri ve
departman tanimlari gibi tekrar yazmak istemeyecegi seyler yerinde kalmalidir.
"""

from __future__ import annotations

from app.infrastructure.seed.demo_data import (
    DEMO_CODE_PREFIX,
    DEMO_EMAIL_DOMAIN,
    DEMO_MARKER,
    DEMO_PROPERTY_CODE,
    DEMO_USERS,
    DEMO_WARNING,
    SCALE_PROFILES,
    DemoClearSummary,
    DemoDataSummary,
    DemoUserCredential,
    DemoUserSpec,
    ScaleProfile,
    clear_demo_data,
    create_demo_data,
)
from app.infrastructure.seed.reference_data import (
    DEPARTMENTS,
    ROOM_FEATURES,
    SERVICES,
    TAX_RATES,
    DepartmentSpec,
    ReferenceDataSummary,
    RoomFeatureSpec,
    ServiceSpec,
    TaxRateSpec,
    ensure_departments,
    ensure_room_features,
    ensure_services,
    ensure_tax_rates,
    seed_reference_data,
)

__all__ = [
    "DEMO_CODE_PREFIX",
    "DEMO_EMAIL_DOMAIN",
    "DEMO_MARKER",
    "DEMO_PROPERTY_CODE",
    "DEMO_USERS",
    "DEMO_WARNING",
    "DEPARTMENTS",
    "ROOM_FEATURES",
    "SCALE_PROFILES",
    "SERVICES",
    "TAX_RATES",
    "DemoClearSummary",
    "DemoDataSummary",
    "DemoUserCredential",
    "DemoUserSpec",
    "DepartmentSpec",
    "ReferenceDataSummary",
    "RoomFeatureSpec",
    "ScaleProfile",
    "ServiceSpec",
    "TaxRateSpec",
    "clear_demo_data",
    "create_demo_data",
    "ensure_departments",
    "ensure_room_features",
    "ensure_services",
    "ensure_tax_rates",
    "seed_reference_data",
]
