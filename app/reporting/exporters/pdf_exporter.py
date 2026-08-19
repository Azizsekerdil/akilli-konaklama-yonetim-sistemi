"""PDF ihracatcisi - reportlab tabanli, Turkce karakter guvenli.

Turkce karakter sorunu ve cozumu
--------------------------------
reportlab'in yerlesik (Type1) yazi tipleri - Helvetica, Times, Courier -
**WinAnsi (cp1252)** kodlamasi kullanir. cp1252 icinde c/o/u sapkali
harfler (U+00E7, U+00F6, U+00FC ve buyukleri) vardir ama Turkce'ye ozgu
yumusak g, s cengelli ve noktasiz i harfleri (U+011F, U+015F, U+0131,
U+0130 ve buyukleri) **yoktur**. Sonuc: "Ucret Turu" yerine bos kutu veya
yanlis harf; bazi surumlerde dogrudan ``UnicodeEncodeError``.

Cozum, gomulebilir bir TrueType yazi tipi kaydetmektir. Aday sirasi:

1. Isletim sistemi yazi tipleri (Windows Arial/Tahoma, Linux DejaVu) -
   Turk Lirasi isareti (U+20BA) dahil tam kapsama.
2. **reportlab ile birlikte gelen Vera** - hicbir sey bulunamazsa bile
   calisir; reportlab zaten bir bagimliliktir, yani bu yol her zaman
   vardir. Vera Turkce harfleri kapsar ama U+20BA isaretini kapsamaz.

Ikinci durumda dosyanin bozuk gorunmemesi icin :func:`sanitize_text`,
yazi tipinde bulunmayan her karakteri okunabilir bir karsiliga cevirir
(U+20BA -> ``TL``). Boylece cikti hicbir kurulumda kirilmaz.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache, partial
from pathlib import Path
from typing import Any

import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.core.log import get_logger
from app.reporting.models import (
    DATETIME_FORMAT,
    EMPTY_TABLE_MESSAGE,
    ReportColumn,
    ReportTable,
    format_cell,
    resolve_export_path,
)

log = get_logger(__name__)

#: Kayitli yazi tipi adlari - reportlab genelinde benzersiz olmalidir.
FONT_REGULAR = "RaporGovde"
FONT_BOLD = "RaporBaslik"

#: Sayfa kenar bosluklari.
MARGIN = 14 * mm

#: Sutun sayisi bunu asinca sayfa yatay (landscape) cevrilir; 8 sutunlu bir
#: tabloyu dikey A4'e sigdirmak metni okunmaz hale getirir.
LANDSCAPE_COLUMN_THRESHOLD = 6

#: Baslik satiri ve tek satir aralarindaki renkler.
HEADER_COLOR = colors.HexColor("#1F4E79")
ROW_ALT_COLOR = colors.HexColor("#F2F6FA")
GRID_COLOR = colors.HexColor("#BFBFBF")

#: Yazi tipinde bulunmayan karakterlerin okunabilir karsiliklari.
#: Kutu karakteri yerine "TL" yazmak, kullaniciya en azindan dogru bilgiyi verir.
_GLYPH_FALLBACK: dict[str, str] = {
    "₺": "TL",
    "€": "EUR",
    "£": "GBP",
    "₽": "RUB",
    "–": "-",
    "—": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "…": "...",
    "\u00a0": " ",
}

#: Bulunamayan ve karsiligi olmayan karakterlerin yerine yazilir.
_UNKNOWN_GLYPH = "?"

_BUNDLED_FONT_DIR = Path(reportlab.__file__).resolve().parent / "fonts"

#: (normal, kalin) yazi tipi dosyasi adaylari - sirayla denenir.
_FONT_CANDIDATES: tuple[tuple[Path, Path], ...] = (
    (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
    (Path("C:/Windows/Fonts/tahoma.ttf"), Path("C:/Windows/Fonts/tahomabd.ttf")),
    (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ),
    (_BUNDLED_FONT_DIR / "Vera.ttf", _BUNDLED_FONT_DIR / "VeraBd.ttf"),
)


@dataclass(frozen=True, slots=True)
class ReportFonts:
    """PDF'te kullanilacak yazi tipleri ve destekledikleri karakterler."""

    regular: str
    bold: str
    supported: frozenset[int]
    """Yazi tipinin kapsadigi Unicode kod noktalari."""

    def supports(self, char: str) -> bool:
        return ord(char) in self.supported


@lru_cache(maxsize=1)
def register_report_fonts() -> ReportFonts:
    """Turkce destekli bir TrueType yazi tipi cifti kaydeder.

    Sonuc onbelleklenir: ayni yazi tipini iki kez kaydetmek reportlab'de
    gereksiz bellek kullanimi ve uyari uretir.

    Adaylardan hicbiri bulunamazsa (kuramsal olarak imkansiz - sonuncusu
    reportlab paketinin icindedir) yerlesik Helvetica'ya donulur; bu
    durumda :func:`sanitize_text` Turkce harfleri de sadelestirir.
    """
    for regular_path, bold_path in _FONT_CANDIDATES:
        if not regular_path.exists():
            continue
        try:
            regular_font = TTFont(FONT_REGULAR, str(regular_path))
            bold_font = TTFont(FONT_BOLD, str(bold_path if bold_path.exists() else regular_path))
            pdfmetrics.registerFont(regular_font)
            pdfmetrics.registerFont(bold_font)
        except Exception as exc:  # pragma: no cover - bozuk yazi tipi dosyasi
            log.warning("pdf_font_yuklenemedi", path=str(regular_path), hata=str(exc))
            continue
        pdfmetrics.registerFontFamily(
            FONT_REGULAR, normal=FONT_REGULAR, bold=FONT_BOLD, italic=FONT_REGULAR
        )
        supported = frozenset(regular_font.face.charToGlyph.keys())
        log.debug("pdf_font_secildi", path=str(regular_path))
        return ReportFonts(FONT_REGULAR, FONT_BOLD, supported)

    # Son care: yerlesik yazi tipi. Yalnizca ASCII guvenli kabul edilir.
    log.warning("pdf_font_bulunamadi", detail="Helvetica'ya donuldu; metin sadelestirilecek.")
    return ReportFonts("Helvetica", "Helvetica-Bold", frozenset(range(0x00, 0x80)))


def sanitize_text(text: str, fonts: ReportFonts) -> str:
    """Yazi tipinde karsiligi olmayan karakterleri gorunur bir esdegerle degistirir.

    >>> f = register_report_fonts()
    >>> sanitize_text("Ucret", f)
    'Ucret'
    """
    if not text:
        return ""
    pieces: list[str] = []
    for char in text:
        if fonts.supports(char):
            pieces.append(char)
            continue
        replacement = _GLYPH_FALLBACK.get(char)
        if replacement is None:
            pieces.append(_UNKNOWN_GLYPH)
            continue
        # Karsilik da desteklenmiyorsa (or. Helvetica'da hicbir sey) ASCII'ye dus.
        pieces.append("".join(c if fonts.supports(c) else _UNKNOWN_GLYPH for c in replacement))
    return "".join(pieces)


def _escape(text: str) -> str:
    """Paragraph icinde kullanilmak uzere kucuk isaretleme kacisi.

    reportlab ``Paragraph`` icerigini mini-XML olarak ayristirir; kacilmayan
    bir ``&`` veya ``<`` tum belgeyi uretilemez hale getirir. ``xml.sax``
    yardimcilarini ice aktarmak yerine uc degisim yeterlidir ve ek bir
    guvenlik yuzeyi acmaz.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _cell_text(value: Any, column: ReportColumn, fonts: ReportFonts) -> str:
    return _escape(sanitize_text(format_cell(value, column), fonts))


def _styles(fonts: ReportFonts) -> dict[str, ParagraphStyle]:
    """Rapor boyunca kullanilan paragraf stilleri."""
    base = ParagraphStyle(
        "RaporHucre",
        fontName=fonts.regular,
        fontSize=8,
        leading=10,
        alignment=TA_LEFT,
    )
    return {
        "title": ParagraphStyle(
            "RaporBaslikMetni",
            parent=base,
            fontName=fonts.bold,
            fontSize=15,
            leading=19,
            spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "RaporAltBaslik", parent=base, fontSize=10, leading=13, textColor=colors.grey
        ),
        "header": ParagraphStyle(
            "RaporSutunBasligi",
            parent=base,
            fontName=fonts.bold,
            textColor=colors.white,
            alignment=TA_CENTER,
        ),
        "note": ParagraphStyle(
            "RaporDipnot", parent=base, fontSize=7.5, leading=10, textColor=colors.grey
        ),
        "left": ParagraphStyle("RaporSol", parent=base, alignment=TA_LEFT),
        "center": ParagraphStyle("RaporOrta", parent=base, alignment=TA_CENTER),
        "right": ParagraphStyle("RaporSag", parent=base, alignment=TA_RIGHT),
    }


def _column_widths(table: ReportTable, available_width: float, fonts: ReportFonts) -> list[float]:
    """Sutun genisliklerini icerik uzunluguna gore orantilar.

    Uzun serbest metin sutunlari (aciklama, baslik) tum genisligi yutmasin
    diye agirlik ust sinira kirpilir; aksi halde sayisal sutunlar okunamaz
    hale gelirdi.
    """
    if not table.columns:
        return []
    weights: list[float] = []
    for column in table.columns:
        widest = len(column.title)
        for row in table.rows[:200]:  # ilk 200 satir olcum icin yeterli
            widest = max(widest, len(format_cell(row.get(column.key), column)))
        weights.append(min(max(widest, 6), 36))
    total = sum(weights)
    return [available_width * weight / total for weight in weights]


def _table_style(table: ReportTable, fonts: ReportFonts) -> TableStyle:
    commands: list[tuple[Any, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_COLOR),
        ("GRID", (0, 0), (-1, -1), 0.4, GRID_COLOR),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("FONTNAME", (0, 0), (-1, -1), fonts.regular),
        ("FONTNAME", (0, 0), (-1, 0), fonts.bold),
    ]
    if table.is_empty:
        # Tek satirlik "Kayit bulunamadi" tum sutunlara yayilir.
        commands.append(("SPAN", (0, 1), (-1, 1)))
    else:
        commands.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT_COLOR]))
    return TableStyle(commands)


def _draw_page(
    canvas: Canvas,
    doc: BaseDocTemplate,
    *,
    table: ReportTable,
    fonts: ReportFonts,
) -> None:
    """Her sayfaya ust bilgi ve alt bilgi cizer.

    Sayfa numarasi ``doc.page`` uzerinden alinir; toplam sayfa sayisi tek
    gecisli uretimde bilinemedigi icin "Sayfa 3 / 7" yerine "Sayfa 3"
    yazilir. Iki gecisli sablon, uzun raporlarda uretim suresini iki
    katina cikarirdi.
    """
    canvas.saveState()
    width, height = doc.pagesize
    header_left = sanitize_text(
        " - ".join(part for part in (table.subtitle, table.title) if part), fonts
    )
    stamp = sanitize_text(f"{table.generated_at.strftime(DATETIME_FORMAT)} (UTC)", fonts)

    canvas.setFont(fonts.bold, 8)
    canvas.setFillColor(colors.HexColor("#404040"))
    canvas.drawString(MARGIN, height - MARGIN + 4, header_left[:110])
    canvas.setFont(fonts.regular, 8)
    canvas.drawRightString(width - MARGIN, height - MARGIN + 4, stamp)
    canvas.setStrokeColor(GRID_COLOR)
    canvas.line(MARGIN, height - MARGIN, width - MARGIN, height - MARGIN)

    canvas.line(MARGIN, MARGIN, width - MARGIN, MARGIN)
    canvas.setFont(fonts.regular, 7.5)
    canvas.setFillColor(colors.grey)
    if table.footer_note:
        canvas.drawString(MARGIN, MARGIN - 10, sanitize_text(table.footer_note, fonts)[:150])
    canvas.drawRightString(width - MARGIN, MARGIN - 10, f"Sayfa {doc.page}")
    canvas.restoreState()


def export(table: ReportTable, output_path: str | os.PathLike[str]) -> Path:
    """Rapor tablosunu A4 PDF olarak yazar ve dosya yolunu dondurur.

    Uzun tablolar otomatik olarak sayfalara bolunur ve sutun basligi her
    sayfada tekrarlanir (``repeatRows=1``); bes sayfalik bir raporda
    baslik gormeden sayilara bakmak ise yaramaz.
    """
    target = resolve_export_path(output_path)
    fonts = register_report_fonts()
    styles = _styles(fonts)

    page_size = landscape(A4) if table.column_count > LANDSCAPE_COLUMN_THRESHOLD else A4
    document = SimpleDocTemplate(
        str(target),
        pagesize=page_size,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN + 8,
        bottomMargin=MARGIN + 8,
        title=sanitize_text(table.title, fonts),
        author="Akilli Konaklama Yonetim Sistemi",
    )
    available_width = page_size[0] - 2 * MARGIN

    story: list[Any] = [Paragraph(_escape(sanitize_text(table.title, fonts)), styles["title"])]
    for text in (table.subtitle, table.filters_description):
        if text:
            story.append(Paragraph(_escape(sanitize_text(text, fonts)), styles["subtitle"]))
    story.append(Spacer(1, 6 * mm))

    header = [
        Paragraph(_escape(sanitize_text(column.title, fonts)), styles["header"])
        for column in table.columns
    ]
    data: list[list[Any]] = [header]
    if table.is_empty:
        empty = [Paragraph(_escape(EMPTY_TABLE_MESSAGE), styles["left"])]
        empty.extend(Paragraph("", styles["left"]) for _ in range(table.column_count - 1))
        data.append(empty)
    else:
        for row in table.rows:
            data.append(
                [
                    Paragraph(_cell_text(row.get(column.key), column, fonts), styles[column.align])
                    for column in table.columns
                ]
            )

    pdf_table = Table(
        data,
        colWidths=_column_widths(table, available_width, fonts),
        repeatRows=1,
    )
    pdf_table.setStyle(_table_style(table, fonts))
    story.append(pdf_table)

    if table.footer_note:
        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph(_escape(sanitize_text(table.footer_note, fonts)), styles["note"]))

    decorate = partial(_draw_page, table=table, fonts=fonts)
    document.build(story, onFirstPage=decorate, onLaterPages=decorate)

    log.info("rapor_disa_aktarildi", bicim="pdf", satir=len(table.rows))
    return target


__all__ = [
    "FONT_BOLD",
    "FONT_REGULAR",
    "LANDSCAPE_COLUMN_THRESHOLD",
    "ReportFonts",
    "export",
    "register_report_fonts",
    "sanitize_text",
]
