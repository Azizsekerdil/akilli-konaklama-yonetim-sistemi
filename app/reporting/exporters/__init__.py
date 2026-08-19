"""Rapor ihracatcilari - CSV, Excel ve PDF.

Uc ihracatci da ayni sozlesmeyi paylasir::

    export(table: ReportTable, output_path: str | PathLike) -> Path

Ortak davranislar:

* Dosya yolu her zaman :data:`app.core.paths.EXPORT_DIR` altinda cozulur;
  disari cikma girisimleri
  :func:`app.reporting.models.resolve_export_path` tarafindan reddedilir.
* Bos tablo **gecerli bir dosya** uretir; icinde "Kayit bulunamadi" satiri
  bulunur. Hicbir ihracatci bos veride hata firlatmaz.
* ``footer_note`` alani, yapay zeka tarafindan uretilen raporlarda
  seffaflik notu ("Bu rapor yapay zeka tarafindan olusturulmustur") tasimak
  icin kullanilir ve ucunde de ciktiya yansir.

Bicim adindan ihracatciya ulasmak icin :func:`get_exporter` kullanilabilir.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from app.core.exceptions import ValidationError
from app.reporting.exporters.csv_exporter import export as export_csv
from app.reporting.exporters.excel_exporter import export as export_excel
from app.reporting.exporters.pdf_exporter import export as export_pdf
from app.reporting.models import ReportTable

#: Bicim adi -> ihracatci fonksiyonu.
EXPORTERS: dict[str, Callable[[ReportTable, str | os.PathLike[str]], Path]] = {
    "csv": export_csv,
    "xlsx": export_excel,
    "excel": export_excel,
    "pdf": export_pdf,
}

#: Bicim adi -> onerilen dosya uzantisi.
EXTENSIONS: dict[str, str] = {"csv": ".csv", "xlsx": ".xlsx", "excel": ".xlsx", "pdf": ".pdf"}


def get_exporter(fmt: str) -> Callable[[ReportTable, str | os.PathLike[str]], Path]:
    """Bicim adindan ihracatci fonksiyonunu dondurur.

    Arayuzdeki "Disa Aktar" menusu bicim adini metin olarak tasir; burada
    bilinmeyen bir bicim, sessizce CSV uretmek yerine anlamli bir hata
    verir.
    """
    key = fmt.strip().lower().lstrip(".")
    exporter = EXPORTERS.get(key)
    if exporter is None:
        raise ValidationError(
            "Desteklenmeyen rapor bicimi.",
            field="format",
            detail=f"Bilinmeyen bicim: {fmt!r}. Gecerli olanlar: {sorted(EXPORTERS)}",
        )
    return exporter


__all__ = [
    "EXPORTERS",
    "EXTENSIONS",
    "export_csv",
    "export_excel",
    "export_pdf",
    "get_exporter",
]
