"""Raporlama ve KPI motoru.

Uc parcadan olusur:

* :mod:`app.reporting.models`   - rapor veri yapilari ve bicimlendirme
* :mod:`app.reporting.kpi`      - saf KPI formulleri (veritabani yok)
* :mod:`app.reporting.queries`  - veritabani sorgulari

Ihracatcilar (:mod:`app.reporting.exporters`) bilerek **buradan iceri
aktarilmaz**: ``openpyxl`` ve ``reportlab`` agir kutuphanelerdir ve yalnizca
rapor disa aktarilirken yuklenmelidir. ``import app.reporting`` yapan bir
arayuz ekrani bu maliyeti odememelidir.

Tipik kullanim::

    from app.domain.value_objects import DateRange
    from app.reporting import kpi_report, occupancy_report
    from app.reporting.exporters import export_excel

    with session_scope(commit=False) as session:
        table = occupancy_report(session, property_id=1, date_range=agustos)
        export_excel(table, "doluluk-agustos.xlsx")
"""

from __future__ import annotations

from app.reporting.kpi import (
    adr,
    alos,
    calculate_kpis,
    cancellation_rate,
    compute_available_room_nights,
    empty_kpis,
    no_show_rate,
    occupancy_rate,
    revpar,
    revpar_from_adr,
    trevpar,
)
from app.reporting.models import (
    EMPTY_TABLE_MESSAGE,
    KPISet,
    ReportColumn,
    ReportTable,
    format_cell,
    format_number,
    resolve_export_path,
)
from app.reporting.queries import (
    arrivals_departures_report,
    daily_closing_report,
    guest_ledger,
    housekeeping_report,
    kpi_report,
    maintenance_report,
    occupancy_report,
    revenue_by_channel,
    revenue_by_charge_type,
    revenue_by_room_type,
    stock_report,
)

__all__ = [
    "EMPTY_TABLE_MESSAGE",
    "KPISet",
    "ReportColumn",
    "ReportTable",
    "adr",
    "alos",
    "arrivals_departures_report",
    "calculate_kpis",
    "cancellation_rate",
    "compute_available_room_nights",
    "daily_closing_report",
    "empty_kpis",
    "format_cell",
    "format_number",
    "guest_ledger",
    "housekeeping_report",
    "kpi_report",
    "maintenance_report",
    "no_show_rate",
    "occupancy_rate",
    "occupancy_report",
    "resolve_export_path",
    "revenue_by_channel",
    "revenue_by_charge_type",
    "revenue_by_room_type",
    "revpar",
    "revpar_from_adr",
    "stock_report",
    "trevpar",
]
