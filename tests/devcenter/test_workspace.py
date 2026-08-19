"""Calisma alani (dosya degisikligi) testleri.

Kritik kural: **onay olmadan diske hicbir sey yazilmaz.**
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.exceptions import DevCenterError, SandboxViolationError
from app.devcenter.workspace import (
    MAX_FILES_PER_CHANGESET,
    ChangeAction,
    Workspace,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "ornek.py").write_text("print('merhaba')\n", encoding="utf-8")
    return Workspace(tmp_path)


class TestYolGuvenligi:
    def test_ust_dizin_kacisi_engellenir(self, workspace: Workspace):
        with pytest.raises(SandboxViolationError):
            workspace.resolve("../../Windows/win.ini")

    def test_mutlak_yol_engellenir(self, workspace: Workspace):
        # NOT: pytest'in `match` parametresi str(exception) uzerinde calisir;
        # HotelError'da bu deger teknik `detail` alanidir (loglara gider).
        # Kullaniciya GOSTERILEN metni dogrulamak icin user_message okunur.
        with pytest.raises(SandboxViolationError) as hata:
            workspace.resolve("C:\\Windows\\win.ini")
        assert "Mutlak yol" in hata.value.user_message

    def test_env_dosyasi_korunur(self, workspace: Workspace):
        with pytest.raises(SandboxViolationError) as hata:
            workspace.resolve(".env")
        assert "korumali" in hata.value.user_message

    def test_git_klasoru_korunur(self, workspace: Workspace):
        with pytest.raises(SandboxViolationError) as hata:
            workspace.resolve(".git/config")
        assert "korumali" in hata.value.user_message

    def test_veritabani_klasoru_korunur(self, workspace: Workspace):
        with pytest.raises(SandboxViolationError):
            workspace.resolve("data/hotel.db")

    def test_veritabani_uzantisi_korunur(self, workspace: Workspace):
        with pytest.raises(SandboxViolationError) as hata:
            workspace.resolve("app/kopya.db")
        assert "uzantili" in hata.value.user_message

    def test_anahtar_dosyasi_korunur(self, workspace: Workspace):
        with pytest.raises(SandboxViolationError):
            workspace.resolve("app/ozel.pem")

    def test_bos_yol_engellenir(self, workspace: Workspace):
        with pytest.raises(SandboxViolationError):
            workspace.resolve("   ")

    def test_gecerli_yol_cozulur(self, workspace: Workspace):
        path = workspace.resolve("app/ornek.py")
        assert path.name == "ornek.py"


class TestDegisiklikHazirlama:
    def test_hazirlama_diske_yazmaz(self, workspace: Workspace):
        """En onemli kural: hazirlamak yazmak degildir."""
        original = workspace.read("app/ornek.py")
        workspace.prepare_change("app/ornek.py", "print('degisti')\n")
        assert workspace.read("app/ornek.py") == original

    def test_yeni_dosya_create_olarak_isaretlenir(self, workspace: Workspace):
        change = workspace.prepare_change("app/yeni.py", "x = 1\n")
        assert change.action is ChangeAction.CREATE
        assert change.original_content is None

    def test_mevcut_dosya_modify_olarak_isaretlenir(self, workspace: Workspace):
        change = workspace.prepare_change("app/ornek.py", "x = 1\n")
        assert change.action is ChangeAction.MODIFY
        assert change.original_content == "print('merhaba')\n"

    def test_silme_hazirlanir(self, workspace: Workspace):
        change = workspace.prepare_change("app/ornek.py", None)
        assert change.action is ChangeAction.DELETE

    def test_olmayan_dosya_silinemez(self, workspace: Workspace):
        with pytest.raises(DevCenterError, match="bulunamadi"):
            workspace.prepare_change("app/yok.py", None)

    def test_var_olan_dosya_create_edilemez(self, workspace: Workspace):
        with pytest.raises(DevCenterError, match="zaten var"):
            workspace.prepare_change("app/ornek.py", "x", action=ChangeAction.CREATE)

    def test_cok_buyuk_dosya_reddedilir(self, workspace: Workspace):
        with pytest.raises(DevCenterError, match="cok buyuk"):
            workspace.prepare_change("app/dev.py", "x" * (600 * 1024))

    def test_cok_fazla_dosya_reddedilir(self, workspace: Workspace):
        files = {f"app/d{i}.py": "x = 1\n" for i in range(MAX_FILES_PER_CHANGESET + 1)}
        with pytest.raises(DevCenterError, match="en fazla"):
            workspace.prepare_changeset(files)


class TestDiff:
    def test_diff_uretilir(self, workspace: Workspace):
        change = workspace.prepare_change("app/ornek.py", "print('degisti')\n")
        diff = change.diff()
        assert "-print('merhaba')" in diff
        assert "+print('degisti')" in diff

    def test_satir_sayilari_hesaplanir(self, workspace: Workspace):
        change = workspace.prepare_change("app/ornek.py", "a\nb\nc\n")
        added, removed = change.line_delta
        assert added == 3
        assert removed == 1

    def test_yeni_dosya_diffinde_dev_null(self, workspace: Workspace):
        change = workspace.prepare_change("app/yeni.py", "x = 1\n")
        assert "/dev/null" in change.diff()

    def test_changeset_toplam_farki(self, workspace: Workspace):
        changeset = workspace.prepare_changeset({"app/ornek.py": "a\nb\n", "app/yeni.py": "c\n"})
        added, removed = changeset.total_delta
        assert added == 3
        assert removed == 1
        assert changeset.file_count == 2


class TestUygulama:
    def test_onaysiz_uygulanamaz(self, workspace: Workspace):
        """KRITIK: onay bayragi olmadan yazma yapilamaz."""
        changeset = workspace.prepare_changeset({"app/ornek.py": "yeni\n"})
        with pytest.raises(DevCenterError, match="onaylanmalidir"):
            workspace.apply(changeset)
        assert workspace.read("app/ornek.py") == "print('merhaba')\n"

    def test_onayli_uygulanir(self, workspace: Workspace):
        changeset = workspace.prepare_changeset({"app/ornek.py": "yeni icerik\n"})
        written = workspace.apply(changeset, approved=True)
        assert written == ["app/ornek.py"]
        assert workspace.read("app/ornek.py") == "yeni icerik\n"

    def test_yeni_dosya_olusturulur(self, workspace: Workspace):
        changeset = workspace.prepare_changeset({"app/alt/yeni.py": "x = 1\n"})
        workspace.apply(changeset, approved=True)
        assert workspace.read("app/alt/yeni.py") == "x = 1\n"

    def test_silme_uygulanir(self, workspace: Workspace, tmp_path: Path):
        changeset = workspace.prepare_changeset({"app/ornek.py": None})
        workspace.apply(changeset, approved=True)
        assert not (tmp_path / "app" / "ornek.py").exists()

    def test_bu_arada_degisen_dosya_reddedilir(self, workspace: Workspace, tmp_path: Path):
        """Kayip guncelleme korumasi: dosya hazirliktan sonra degistiyse dur."""
        changeset = workspace.prepare_changeset({"app/ornek.py": "ai versiyonu\n"})

        # Kullanici bu arada dosyayi elle degistirdi.
        (tmp_path / "app" / "ornek.py").write_text("kullanici versiyonu\n", encoding="utf-8")

        with pytest.raises(DevCenterError, match="baskasi tarafindan degistirildi"):
            workspace.apply(changeset, approved=True)

        # Kullanicinin degisikligi KORUNMALI
        assert workspace.read("app/ornek.py") == "kullanici versiyonu\n"

    def test_kismi_yazma_olmaz(self, workspace: Workspace, tmp_path: Path):
        """Bir dosya bayatsa HICBIRI yazilmaz."""
        changeset = workspace.prepare_changeset(
            {"app/ornek.py": "yeni1\n", "app/ikinci.py": "yeni2\n"}
        )
        (tmp_path / "app" / "ornek.py").write_text("elle degisti\n", encoding="utf-8")

        with pytest.raises(DevCenterError):
            workspace.apply(changeset, approved=True)

        # Ikinci dosya da YAZILMAMIS olmali
        assert not (tmp_path / "app" / "ikinci.py").exists()
