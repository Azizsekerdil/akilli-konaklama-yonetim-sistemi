"""``format_path`` gerileme testleri.

Yayin oncesi denetimde tanitim sunumundaki AI Gelistirme Merkezi ekraninin
tam dosya yolunu - ve icindeki Windows kullanici adini - gosterdigi tespit
edildi. Ekran goruntusu ve destek ciktilari gereksiz bir kisisel tanimlayici
tasimamalidir.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.ui.formatting import format_path

pytestmark = pytest.mark.unit


def test_ev_dizini_tilde_ile_degistirilir():
    ev = Path(os.path.expanduser("~"))
    sonuc = format_path(ev / "proje" / "hotel")
    assert sonuc.startswith("~")
    assert ev.name not in sonuc


def test_kullanici_adi_sizmaz():
    ev = os.path.expanduser("~")
    kullanici = os.path.basename(ev)
    sonuc = format_path(os.path.join(ev, "AppData", "Local", "Temp", "x"))
    assert kullanici not in sonuc


def test_ev_disindaki_yol_degismez():
    yol = Path("D:/Projeler/hotel") if os.name == "nt" else Path("/srv/hotel")
    assert format_path(yol) == str(yol)


def test_bos_ve_goreli_yollar_guvenli():
    assert format_path("app/main.py") == "app/main.py"
    assert format_path(Path(".")) == "."
