"""Gelistirme oturumu ve Git guvenlik agi testleri.

Bu testler gercek bir Git deposu olusturur (tmp_path icinde) ve akisi ucdan
uca dogrular: kontrol noktasi -> dal -> diff -> onay -> uygulama -> kalite
kapisi -> commit / geri alma.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.application.context import ServiceContext
from app.core.exceptions import AuthorizationError, DevCenterError
from app.devcenter.git_guard import GitGuard
from app.devcenter.quality import (
    QualityReport,
    QualityStep,
    StepOutcome,
    StepResult,
)
from app.devcenter.session import DevSession, SessionState

pytestmark = pytest.mark.integration


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Icinde tek commit bulunan gercek bir Git deposu."""
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@ornek-test.local")
    _git(tmp_path, "config", "user.name", "Test")

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "ornek.py").write_text("VERSIYON = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "ilk")
    return tmp_path


@pytest.fixture
def dev_session(admin_ctx: ServiceContext, repo: Path) -> DevSession:
    """Gercek bir Git deposu uzerinde calisan gelistirme oturumu.

    Adi bilerek ``dev_session``: ``session`` adi conftest.py'deki veritabani
    oturumu fikstürünü golgeler ve ozyinelemeli bagimlilik hatasi uretir.
    """
    return DevSession(admin_ctx, repo)


class TestGitGuard:
    def test_depo_algilanir(self, repo: Path):
        assert GitGuard(repo).is_repository()

    def test_depo_olmayan_klasor(self, tmp_path: Path):
        assert not GitGuard(tmp_path / "bos").is_repository()

    def test_durum_temiz(self, repo: Path):
        status = GitGuard(repo).status()
        assert status.is_clean
        assert status.branch == "main"
        assert status.is_protected_branch

    def test_durum_degisiklikleri_gorur(self, repo: Path):
        (repo / "app" / "ornek.py").write_text("VERSIYON = 2\n", encoding="utf-8")
        status = GitGuard(repo).status()
        assert not status.is_clean
        assert "app/ornek.py" in status.modified

    def test_kontrol_noktasi_calisma_agacini_bozmaz(self, repo: Path):
        """git stash create kullanilmali; push kullanilsa dosyalar geri alinirdi."""
        (repo / "app" / "ornek.py").write_text("VERSIYON = 2\n", encoding="utf-8")
        guard = GitGuard(repo)
        checkpoint = guard.create_checkpoint()

        assert checkpoint.can_restore
        # Dosya HALA degismis durumda olmali
        assert (repo / "app" / "ornek.py").read_text(encoding="utf-8") == "VERSIYON = 2\n"

    def test_temiz_agacta_kontrol_noktasi_bos(self, repo: Path):
        checkpoint = GitGuard(repo).create_checkpoint()
        assert not checkpoint.had_changes
        assert not checkpoint.can_restore

    def test_gorev_dali_olusturulur(self, repo: Path):
        guard = GitGuard(repo)
        branch = guard.create_task_branch("Rezervasyon ekranina filtre ekle")
        assert branch.startswith("ai/")
        assert "rezervasyon" in branch
        assert guard.current_branch() == branch

    def test_korunan_dal_silinemez(self, repo: Path):
        with pytest.raises(DevCenterError, match="korunan"):
            GitGuard(repo).delete_branch("main")

    def test_slugify_turkce_karakterleri_cevirir(self):
        assert GitGuard.slugify("Çağrı Şubesi Güncelle") == "cagri-subesi-guncelle"
        assert GitGuard.slugify("!!!") == "gorev"


class TestOturumAkisi:
    def test_gorev_baslatilir(self, dev_session: DevSession):
        dev_session.start("Test gorevi")
        assert dev_session.state is SessionState.PREPARING
        assert dev_session.branch and dev_session.branch.startswith("ai/")
        assert dev_session.base_branch == "main"
        assert dev_session.checkpoint is not None

    def test_bos_gorev_reddedilir(self, dev_session: DevSession):
        with pytest.raises(DevCenterError):
            dev_session.start("   ")

    def test_git_olmayan_klasorde_baslamaz(self, admin_ctx: ServiceContext, tmp_path: Path):
        bos = tmp_path / "gitsiz"
        bos.mkdir()
        with pytest.raises(DevCenterError, match="Git deposu degil"):
            DevSession(admin_ctx, bos).start("Gorev")

    def test_ikinci_gorev_devam_ederken_baslamaz(self, dev_session: DevSession):
        dev_session.start("Birinci")
        with pytest.raises(DevCenterError, match="tamamlanmadi"):
            dev_session.start("Ikinci")

    def test_degisiklik_onerisi_diske_yazmaz(self, dev_session: DevSession, repo: Path):
        dev_session.start("Test")
        dev_session.propose({"app/ornek.py": "VERSIYON = 2\n"})

        assert dev_session.state is SessionState.AWAITING_APPROVAL
        assert (repo / "app" / "ornek.py").read_text(encoding="utf-8") == "VERSIYON = 1\n"

    def test_onaysiz_uygulama_reddedilir(self, dev_session: DevSession, repo: Path):
        dev_session.start("Test")
        dev_session.propose({"app/ornek.py": "VERSIYON = 2\n"})

        with pytest.raises(DevCenterError, match="onaylanmalidir"):
            dev_session.apply(approved=False)
        assert (repo / "app" / "ornek.py").read_text(encoding="utf-8") == "VERSIYON = 1\n"

    def test_onayli_uygulama_yazar(self, dev_session: DevSession, repo: Path):
        dev_session.start("Test")
        dev_session.propose({"app/ornek.py": "VERSIYON = 2\n"})
        written = dev_session.apply(approved=True)

        assert written == ["app/ornek.py"]
        assert dev_session.state is SessionState.APPLIED
        assert (repo / "app" / "ornek.py").read_text(encoding="utf-8") == "VERSIYON = 2\n"

    def test_baslamadan_oneri_yapilamaz(self, dev_session: DevSession):
        with pytest.raises(DevCenterError, match="gorev baslatilmalidir"):
            dev_session.propose({"app/x.py": "x\n"})


class TestKaliteKapisi:
    """Testler gecmeden commit yapilamaz - en onemli kural."""

    def test_dogrulanmadan_commit_yapilamaz(self, dev_session: DevSession):
        dev_session.start("Test")
        dev_session.propose({"app/ornek.py": "VERSIYON = 2\n"})
        dev_session.apply(approved=True)

        with pytest.raises(DevCenterError, match="Kalite kontrolleri gecmeden"):
            dev_session.commit("feat: degisiklik")

    def test_dogrulama_sonrasi_commit_yapilir(self, dev_session: DevSession, monkeypatch):
        dev_session.start("Test")
        dev_session.propose({"app/ornek.py": "VERSIYON = 2\n"})
        dev_session.apply(approved=True)

        monkeypatch.setattr(
            "app.devcenter.session.run_quality_chain",
            lambda **kwargs: _gecen_rapor(),
        )
        report = dev_session.verify()
        assert report.blocking_passed
        assert dev_session.state is SessionState.VERIFIED

        sha = dev_session.commit("feat: surum guncellendi")
        assert len(sha) == 40
        assert dev_session.state is SessionState.COMMITTED

    def test_basarisiz_testte_degisiklik_geri_alinir(
        self, dev_session: DevSession, repo: Path, monkeypatch
    ):
        """KRITIK: kalite zinciri gecmezse degisiklik kalici olmaz."""
        dev_session.start("Test")
        dev_session.propose({"app/ornek.py": "BOZUK KOD\n"})
        dev_session.apply(approved=True)
        assert (repo / "app" / "ornek.py").read_text(encoding="utf-8") == "BOZUK KOD\n"

        monkeypatch.setattr(
            "app.devcenter.session.run_quality_chain",
            lambda **kwargs: _basarisiz_rapor(),
        )
        report = dev_session.verify_and_commit("feat: olmayacak")

        assert report.state is SessionState.ABORTED
        assert not report.succeeded
        assert "geri alindi" in report.message
        # Dosya ESKI haline donmus olmali
        assert (repo / "app" / "ornek.py").read_text(encoding="utf-8") == "VERSIYON = 1\n"
        assert GitGuard(repo).current_branch() == "main"


class TestBirlestirme:
    def test_onaysiz_birlestirme_reddedilir(self, dev_session: DevSession, monkeypatch):
        dev_session.start("Test")
        dev_session.propose({"app/ornek.py": "VERSIYON = 2\n"})
        dev_session.apply(approved=True)
        monkeypatch.setattr(
            "app.devcenter.session.run_quality_chain", lambda **kwargs: _gecen_rapor()
        )
        dev_session.verify()
        dev_session.commit("feat: x")

        with pytest.raises(DevCenterError, match="acik onay"):
            dev_session.merge_to_base(approved=False)

    def test_islenmemis_gorev_birlestirilemez(self, dev_session: DevSession):
        dev_session.start("Test")
        with pytest.raises(DevCenterError, match="islenmis"):
            dev_session.merge_to_base(approved=True)

    def test_onayli_birlestirme_calisir(self, dev_session: DevSession, repo: Path, monkeypatch):
        dev_session.start("Test")
        dev_session.propose({"app/ornek.py": "VERSIYON = 2\n"})
        dev_session.apply(approved=True)
        monkeypatch.setattr(
            "app.devcenter.session.run_quality_chain", lambda **kwargs: _gecen_rapor()
        )
        dev_session.verify()
        dev_session.commit("feat: surum")

        dev_session.merge_to_base(approved=True)
        guard = GitGuard(repo)
        assert guard.current_branch() == "main"
        assert (repo / "app" / "ornek.py").read_text(encoding="utf-8") == "VERSIYON = 2\n"


class TestGeriAlma:
    def test_iptal_degisiklikleri_geri_alir(self, dev_session: DevSession, repo: Path):
        dev_session.start("Test")
        dev_session.propose({"app/ornek.py": "YANLIS\n"})
        dev_session.apply(approved=True)

        dev_session.abort(reason="Kullanici vazgecti")

        assert dev_session.state is SessionState.ABORTED
        assert (repo / "app" / "ornek.py").read_text(encoding="utf-8") == "VERSIYON = 1\n"
        assert GitGuard(repo).current_branch() == "main"

    def test_iptal_sonrasi_yeni_gorev_baslatilabilir(self, dev_session: DevSession):
        dev_session.start("Birinci")
        dev_session.abort()
        dev_session.start("Ikinci")
        assert dev_session.state is SessionState.PREPARING


class TestYetkilendirme:
    def test_yetkisiz_kullanici_gorev_baslatamaz(
        self, secured_session, frontdesk_user, repo: Path, sample_property
    ):
        ctx = ServiceContext(
            session=secured_session, user=frontdesk_user, property_id=sample_property.id
        )
        with pytest.raises(AuthorizationError):
            DevSession(ctx, repo).start("Gorev")

    def test_yetkisiz_kullanici_komut_calistiramaz(
        self, secured_session, frontdesk_user, repo: Path, sample_property, admin_ctx
    ):
        # Gorevi yonetici baslatir
        started = DevSession(admin_ctx, repo)
        started.start("Test")

        # Sonra yetkisiz kullanici komut calistirmaya calisir
        started.ctx = ServiceContext(
            session=secured_session, user=frontdesk_user, property_id=sample_property.id
        )
        with pytest.raises(AuthorizationError):
            started.run("git status")


class TestDenetimKaydi:
    def test_gorev_baslatma_denetime_yazilir(self, dev_session: DevSession, admin_ctx):
        from sqlalchemy import select

        from app.infrastructure.db.models.security import AuditLog

        dev_session.start("Denetim testi")
        admin_ctx.session.flush()

        kayitlar = admin_ctx.session.scalars(
            select(AuditLog).where(AuditLog.entity_type == "DevSession")
        ).all()
        assert len(kayitlar) >= 1
        assert "Denetim testi" in kayitlar[0].description


# --------------------------------------------------------------------------
#  Yardimcilar
# --------------------------------------------------------------------------
def _gecen_rapor() -> QualityReport:
    step = QualityStep(key="test", title="Testler", command="pytest", blocking=True)
    return QualityReport(steps=[StepResult(step=step, outcome=StepOutcome.PASSED)])


def _basarisiz_rapor() -> QualityReport:
    step = QualityStep(key="test", title="Testler", command="pytest", blocking=True)
    return QualityReport(
        steps=[StepResult(step=step, outcome=StepOutcome.FAILED, detail="3 test basarisiz")]
    )
