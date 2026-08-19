"""CSV ihracatcisi - Turkce Windows Excel ile uyumlu.

Iki karar bu dosyanin tamamini aciklar:

**1. UTF-8 BOM (``utf-8-sig``)**
   Excel, uzantisi ``.csv`` olan bir dosyayi cift tiklayarak actiginda
   icerigi UTF-8 varsaymaz; isletim sisteminin ANSI kod sayfasini (Turkce
   Windows'ta cp1254) kullanir. BOM'suz yazilan bir dosyada "Ucret Turu"
   yerine "Ãœcret TÃ¼rÃ¼" gorunur ve kullanici dosyanin bozuk oldugunu
   dusunur. Basa eklenen uc baytlik BOM (``EF BB BF``), Excel'e "bu dosya
   UTF-8" der ve sorun tumuyle ortadan kalkar.

**2. Noktali virgul ayirici**
   Turkce yerel ayarda ondalik ayirici virguldur (``1.234,56``). Virgulle
   ayrilmis bir CSV'de ``1.234,56`` iki hucreye bolunur. Windows'un Turkce
   yerelinde Excel'in bekledigi liste ayiricisi zaten noktali virguldur.

Ucuncu bir karar da guvenlikle ilgilidir: her hucre yazilmadan once
:func:`app.reporting.models.neutralize_formula` ile CSV enjeksiyonuna karsi
etkisizlestirilir. Gerekce o fonksiyonun docstring'indedir.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from app.core.log import get_logger
from app.reporting.models import ReportTable, neutralize_formula, resolve_export_path

log = get_logger(__name__)

#: Excel'e "bu dosya UTF-8" diyen kodlama (BOM ekler).
CSV_ENCODING = "utf-8-sig"

#: Turkce Windows Excel'in varsayilan liste ayiricisi.
CSV_DELIMITER = ";"

#: Excel, satir sonu olarak CRLF bekler; LF ile yazilan dosyalar bazi
#: surumlerde tek satir gibi acilir.
CSV_LINE_TERMINATOR = "\r\n"


def _safe_row(cells: list[str]) -> list[str]:
    """Satirin her hucresini formul enjeksiyonuna karsi etkisizlestirir."""
    return [neutralize_formula(cell) for cell in cells]


def export(table: ReportTable, output_path: str | os.PathLike[str]) -> Path:
    """Rapor tablosunu CSV olarak yazar ve dosya yolunu dondurur.

    Bos tabloda dosya yine de uretilir: baslik satiri ve tek bir
    "Kayit bulunamadi" satiri yazilir. Bos bir dosya, raporun calismadigi
    izlenimi verirdi.
    """
    target = resolve_export_path(output_path)

    # newline="" zorunludur: csv modulu satir sonunu kendi yazar, aksi halde
    # Windows'ta her satir arasinda bos satir olusur.
    with target.open("w", encoding=CSV_ENCODING, newline="") as handle:
        writer = csv.writer(
            handle,
            delimiter=CSV_DELIMITER,
            lineterminator=CSV_LINE_TERMINATOR,
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writerow(_safe_row(table.header_titles))
        if table.is_empty:
            writer.writerow(_safe_row(table.empty_row()))
        else:
            writer.writerows(_safe_row(row) for row in table.display_rows())
        if table.footer_note:
            # Dipnot "#" ile isaretlenir; boylece veri satiri sanilmaz.
            writer.writerow([f"# {table.footer_note}"])

    log.info("rapor_disa_aktarildi", bicim="csv", satir=len(table.rows))
    return target


__all__ = ["CSV_DELIMITER", "CSV_ENCODING", "CSV_LINE_TERMINATOR", "export"]
