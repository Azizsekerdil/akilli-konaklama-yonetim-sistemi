"""Uygulama simgesini (.ico) uretir.

Neden kod ile uretiliyor?
-------------------------
Ikili (binary) bir ikon dosyasini depoya koymak yerine kaynaktan uretmek
uc avantaj saglar: dosya surum kontrolunde okunabilir kalir, tema renkleri
degistiginde simge de guncellenebilir, ve ek bir tasarim araci gerekmez.

Windows'un ihtiyac duydugu tum boyutlar (16-256 px) tek dosyada toplanir;
gorev cubugu, masaustu kisayolu ve pencere baslik cubugu farkli boyutlari
kullanir.

Calistirma::

    .\\.venv\\Scripts\\python.exe packaging\\make_icon.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import QApplication

#: Windows'un kullandigi ikon boyutlari.
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)

#: Marka renkleri (app/ui/theme.py ile uyumlu).
BRAND_START = "#1B5E9E"
BRAND_END = "#4A9EE0"
ACCENT = "#FFFFFF"


def draw_icon(size: int) -> QPixmap:
    """Tek bir boyut icin simge cizer.

    Tasarim: yuvarlatilmis kare zemin uzerinde stilize bir bina silueti
    (konaklama) ve kucuk boyutlarda okunabilirligi koruyan sade hatlar.
    16 px'te ayrinti taninmayacagi icin yalnizca harf gosterilir.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # --- Zemin ---
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, QColor(BRAND_START))
    gradient.setColorAt(1.0, QColor(BRAND_END))
    painter.setBrush(QBrush(gradient))
    painter.setPen(Qt.PenStyle.NoPen)
    radius = size * 0.22
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)

    painter.setBrush(QBrush(QColor(ACCENT)))

    if size <= 24:
        # Kucuk boyutta ayrinti okunmaz; yalnizca harf.
        painter.setPen(QColor(ACCENT))
        font = QFont("Segoe UI", int(size * 0.55))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "K"
        )
    else:
        # --- Bina silueti ---
        unit = size / 32.0
        building_x = 9 * unit
        building_y = 8 * unit
        building_w = 14 * unit
        building_h = 17 * unit
        painter.drawRect(QRectF(building_x, building_y, building_w, building_h))

        # --- Pencereler (zemin renginde oyulmus) ---
        painter.setBrush(QBrush(QColor(BRAND_START)))
        window_size = 2.2 * unit
        gap = 1.6 * unit
        start_x = building_x + gap
        start_y = building_y + gap

        for row in range(4):
            for column in range(3):
                # En alt orta pencere kapi olur
                if row == 3 and column == 1:
                    continue
                painter.drawRect(
                    QRectF(
                        start_x + column * (window_size + gap * 0.7),
                        start_y + row * (window_size + gap * 0.55),
                        window_size,
                        window_size,
                    )
                )

        # --- Kapi ---
        door_w = 3 * unit
        door_h = 4.5 * unit
        painter.drawRect(
            QRectF(
                building_x + building_w / 2 - door_w / 2,
                building_y + building_h - door_h,
                door_w,
                door_h,
            )
        )

    painter.end()
    return pixmap


def main() -> int:
    app = QApplication(sys.argv)

    target_dir = Path(__file__).resolve().parents[1] / "app" / "ui" / "resources" / "icons"
    target_dir.mkdir(parents=True, exist_ok=True)

    pixmaps = [draw_icon(size) for size in ICON_SIZES]

    # En buyuk boyutu PNG olarak da kaydet (belgeler ve README icin).
    png_path = target_dir / "app.png"
    pixmaps[-1].save(str(png_path), "PNG")

    # Cok boyutlu .ico
    ico_path = target_dir / "app.ico"
    writer_ok = _write_ico(ico_path, pixmaps)

    print(f"PNG : {png_path}")
    print(f"ICO : {ico_path} ({'olusturuldu' if writer_ok else 'BASARISIZ'})")
    del app
    return 0 if writer_ok else 1


def _write_ico(path: Path, pixmaps: list[QPixmap]) -> bool:
    """Cok boyutlu ICO dosyasi yazar.

    Qt'nin ICO yazicisi yalnizca tek boyut kaydeder; Windows'un farkli
    baglamlarda (gorev cubugu, masaustu, alt+tab) farkli boyutlara ihtiyaci
    oldugu icin ICO bicimini elle olusturuyoruz. Her goruntu PNG olarak
    gomulur - Vista sonrasi Windows bunu destekler ve dosya kucuk kalir.
    """
    import struct
    from io import BytesIO

    from PySide6.QtCore import QBuffer, QByteArray

    images: list[tuple[int, bytes]] = []
    for pixmap in pixmaps:
        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        if not pixmap.save(buffer, "PNG"):
            return False
        buffer.close()
        images.append((pixmap.width(), bytes(byte_array)))

    output = BytesIO()
    # ICONDIR: reserved(0), type(1=ico), count
    output.write(struct.pack("<HHH", 0, 1, len(images)))

    offset = 6 + 16 * len(images)
    for width, data in images:
        # 256 px, ICO bicinminde 0 olarak kodlanir
        dimension = 0 if width >= 256 else width
        output.write(
            struct.pack(
                "<BBBBHHII",
                dimension,  # genislik
                dimension,  # yukseklik
                0,  # palet rengi yok
                0,  # ayrilmis
                1,  # renk duzlemi
                32,  # bit/piksel
                len(data),
                offset,
            )
        )
        offset += len(data)

    for _, data in images:
        output.write(data)

    path.write_bytes(output.getvalue())
    return True


if __name__ == "__main__":
    raise SystemExit(main())
