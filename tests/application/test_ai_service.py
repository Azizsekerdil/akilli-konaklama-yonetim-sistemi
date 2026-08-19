"""Yapay zeka servisi testleri - GERCEK AG CAGRISI YOK.

Tum testler :class:`~app.ai.providers.mock.MockProvider` ile calisir; saglayici
kaydi (``ProviderRegistry``) testin kendi fabrikalariyla kurulur. Boylece hicbir
test LM Studio'nun acik olmasina, internete ya da bir API anahtarina bagli
degildir.

Burada sinanan sozlesmeler:

* **Gizlilik** - gunluk ozet isteminde misafir adi, kimlik numarasi, e-posta
  ve telefon YOKTUR (``TestGizlilik``).
* **Salt okunurluk** - fiyat onerisi hicbir fiyati degistirmez ve
  ``applied`` her zaman ``False``'tur (``TestFiyatOnerisi``).
* **Hesap verebilirlik** - basarili ve basarisiz her cagri ``AIUsage``
  tablosuna yazilir (``TestKullanimKaydi``).
* **Anlasilir hata** - saglayici hatasi Turkce mesaj + cozum onerisiyle
  doner (``TestHataCevirisi``).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.ai.providers.mock import MockProvider
from app.ai.registry import ProviderRegistry
from app.ai.types import ChatMessage
from app.application.context import ServiceContext
from app.application.services.ai_service import (
    AI_GENERATED_MARKER,
    PRICING_ADVISORY_NOTE,
    AIService,
    DraftKind,
    assert_prompt_is_anonymous,
    find_personal_data,
    redact_personal_data,
)
from app.application.services.reservation_service import ReservationService, RoomRequest
from app.core.config import AISettings, ProviderName
from app.core.exceptions import (
    AIConnectionError,
    AIResponseFormatError,
    AITimeoutError,
    AuthorizationError,
    ConfigurationError,
    ValidationError,
)
from app.domain.enums import AITaskType, AIUsageStatus
from app.domain.value_objects import DateRange
from app.infrastructure.db.models.ai import AIUsage
from app.infrastructure.db.models.rooms import RoomType

pytestmark = pytest.mark.ai


# --------------------------------------------------------------------------
#  Yardimcilar
# --------------------------------------------------------------------------
def ai_settings(**kwargs) -> AISettings:
    """Testler icin ACIKCA etkinlestirilmis ayarlar.

    Test ortaminda ``HOTEL_AI_ENABLED=false``'tur (bkz. tests/conftest.py);
    servisin acik yapay zeka davranisini sinamak icin ayarlar burada bilincli
    olarak enjekte edilir - ortam degiskeni degistirilmez.
    """
    kwargs.setdefault("enabled", True)
    kwargs.setdefault("primary_provider", ProviderName.LMSTUDIO)
    kwargs.setdefault("fallback_provider", None)
    return AISettings(**kwargs)


def make_registry(
    provider: MockProvider,
    *,
    fallback: MockProvider | None = None,
    settings: AISettings | None = None,
) -> ProviderRegistry:
    """Sahte saglayicilarla kurulmus kayit."""
    factories = {ProviderName.LMSTUDIO: lambda _s: provider}
    if fallback is not None:
        factories[ProviderName.MOCK] = lambda _s: fallback
    return ProviderRegistry(settings or ai_settings(), factories=factories)


def make_service(
    ctx: ServiceContext,
    provider: MockProvider | None = None,
    **registry_kwargs,
) -> AIService:
    mock = provider if provider is not None else MockProvider(responses=["Gunluk ozet metni."])
    return AIService(ctx, registry=make_registry(mock, **registry_kwargs))


def usages(ctx: ServiceContext) -> list[AIUsage]:
    return list(ctx.session.scalars(select(AIUsage).order_by(AIUsage.id)).all())


def prompt_text(provider: MockProvider) -> str:
    """Saglayiciya gonderilen tum istem metinlerinin birlesimi."""
    return "\n".join(message.content for request in provider.calls for message in request.messages)


@pytest.fixture
def ai_property(property_with_rooms):
    """Oda ve fiyat plani hazir tesis (okunabilir takma ad)."""
    return property_with_rooms


@pytest.fixture
def viewer_ctx(secured_session, sample_property):
    """Yapay zeka yetkisi OLMAYAN kullanicinin baglami ('viewer' rolu)."""
    from app.infrastructure.db.models import Role, User
    from app.security.passwords import hash_password

    role = secured_session.scalars(select(Role).where(Role.code == "viewer")).one()
    user = User(
        username="izleyici",
        full_name="Test Izleyici",
        password_hash=hash_password("IzleyiciTest2026!"),
        is_superuser=False,
    )
    user.roles.append(role)
    secured_session.add(user)
    secured_session.commit()
    return ServiceContext(session=secured_session, user=user, property_id=sample_property.id)


# ==========================================================================
#  Gizlilik
# ==========================================================================
class TestGizlilik:
    def test_gunluk_ozet_istemi_misafir_bilgisi_icermez(
        self, admin_ctx, ai_property, sample_room_type, sample_rooms, guest, next_week
    ):
        """Modele giden istemde ad, kimlik, e-posta ve telefon BULUNMAZ."""
        ReservationService(admin_ctx).create_reservation(
            guest_id=guest.id,
            room_requests=[
                RoomRequest(
                    room_type_id=sample_room_type.id,
                    room_id=sample_rooms[0].id,
                    check_in=next_week,
                    check_out=next_week + timedelta(days=2),
                )
            ],
        )
        provider = MockProvider(responses=["Ozet"])
        service = make_service(admin_ctx, provider)

        service.daily_summary(next_week)

        gonderilen = prompt_text(provider)
        # Rezervasyon gercekten donemde: sayim istemde gorunmeli.
        assert '"giris_sayisi": 1' in gonderilen

        for yasak in (
            guest.first_name,
            guest.last_name,
            "deniz.yildizli@ornek-test.local",
            "11111111110",
            "+90 555 000 00 01",
        ):
            assert yasak not in gonderilen, f"Istemde kisisel veri sizdi: {yasak!r}"

    def test_gunluk_veri_yapisi_yalnizca_sayi_icerir(self, admin_ctx, ai_property):
        """DailyFacts govdesinde tarih ve para birimi disinda metin yoktur."""
        service = make_service(admin_ctx)
        payload = service.collect_daily_facts().to_payload()

        metinler = {k: v for k, v in payload.items() if isinstance(v, str)}
        assert set(metinler) == {"gun", "para_birimi"}
        assert all(isinstance(v, (int, float)) for k, v in payload.items() if k not in metinler)

    def test_serbest_metinde_iletisim_bilgisi_maskelenir(self, admin_ctx, ai_property):
        provider = MockProvider(responses=["Taslak"])
        service = make_service(admin_ctx, provider)

        service.draft_message(
            DraftKind.COMPLAINT_RESPONSE,
            {"durum": "Misafir deniz@ornek-test.local adresinden 11111111110 ile yazdi."},
        )

        gonderilen = prompt_text(provider)
        assert "deniz@ornek-test.local" not in gonderilen
        assert "11111111110" not in gonderilen
        assert "[e-posta gizlendi]" in gonderilen

    def test_kisisel_veri_kalirsa_cagri_yapilmadan_engellenir(self):
        """Son savunma hatti: yapisal kurgu bozulursa istem gonderilmez."""
        with pytest.raises(ValidationError) as hata:
            assert_prompt_is_anonymous([ChatMessage.user("Iletisim: kisi@ornek.local")])
        assert hata.value.code == "ai_prompt_contains_pii"
        # Bulgunun kendisi hata metnine yazilmaz.
        assert "kisi@ornek.local" not in hata.value.user_message

    def test_maskeleme_para_tutarlarini_bozmaz(self):
        """Buyuk ciro sayilari telefon/kimlik sanilmaz (yanlis pozitif yok)."""
        govde = '{"toplam_gelir": 1234567890.0, "adr": 987654321.55, "gun": "2026-08-15"}'
        assert find_personal_data(govde) == []
        assert redact_personal_data(govde) == govde

    def test_maskeleme_gercek_verileri_yakalar(self):
        temiz = redact_personal_data("Kart 4111111111111111, tel 0555 123 45 67, a@b.co")
        assert "4111111111111111" not in temiz
        assert "0555 123 45 67" not in temiz
        assert "a@b.co" not in temiz


# ==========================================================================
#  Kullanim kaydi
# ==========================================================================
class TestKullanimKaydi:
    def test_basarili_cagri_kaydedilir(self, admin_ctx, ai_property):
        service = make_service(admin_ctx, MockProvider(responses=["Ozet metni"]))

        sonuc = service.daily_summary()

        kayitlar = usages(admin_ctx)
        assert len(kayitlar) == 1
        kayit = kayitlar[0]
        assert kayit.status is AIUsageStatus.SUCCESS
        assert kayit.task_type is AITaskType.DAILY_SUMMARY
        assert kayit.user_id == admin_ctx.user_id
        assert kayit.total_tokens > 0
        assert sonuc.usage_id == kayit.id
        assert sonuc.is_ai_generated is True

    def test_basarisiz_cagri_da_kaydedilir(self, admin_ctx, ai_property):
        service = make_service(
            admin_ctx, MockProvider(fail_with=AIConnectionError(provider="lmstudio"))
        )

        with pytest.raises(AIConnectionError):
            service.daily_summary()

        kayitlar = usages(admin_ctx)
        assert len(kayitlar) == 1
        assert kayitlar[0].status is AIUsageStatus.FAILED
        assert kayitlar[0].error_code == "ai_connection_error"
        assert kayitlar[0].error_message

    def test_zaman_asimi_ayri_durumla_kaydedilir(self, admin_ctx, ai_property):
        service = make_service(
            admin_ctx, MockProvider(fail_with=AITimeoutError(provider="lmstudio"))
        )

        with pytest.raises(AITimeoutError):
            service.daily_summary()

        assert usages(admin_ctx)[0].status is AIUsageStatus.TIMEOUT

    def test_yedege_gecilen_cagri_isaretlenir(self, admin_ctx, ai_property):
        birincil = MockProvider(fail_with=AIConnectionError(provider="lmstudio"))
        yedek = MockProvider(responses=["Yedekten yanit"])
        service = AIService(
            admin_ctx,
            registry=make_registry(
                birincil,
                fallback=yedek,
                settings=ai_settings(fallback_provider=ProviderName.MOCK),
            ),
        )

        sonuc = service.daily_summary()

        assert sonuc.used_fallback is True
        kayit = usages(admin_ctx)[0]
        assert kayit.status is AIUsageStatus.FALLBACK_USED
        assert kayit.fell_back_from == ProviderName.LMSTUDIO.value

    def test_denetim_kaydi_yazilir(self, admin_ctx, ai_property):
        from app.domain.enums import AuditAction
        from app.infrastructure.db.models.security import AuditLog

        make_service(admin_ctx).daily_summary()

        kayitlar = admin_ctx.session.scalars(
            select(AuditLog).where(AuditLog.action == AuditAction.AI_REQUEST)
        ).all()
        assert len(kayitlar) == 1


# ==========================================================================
#  Yetki ve devre disi durumu
# ==========================================================================
class TestYetkiVeDurum:
    def test_yetkisiz_kullanici_yapay_zeka_kullanamaz(self, viewer_ctx, ai_property):
        service = make_service(viewer_ctx)

        with pytest.raises(AuthorizationError) as hata:
            service.daily_summary()
        assert hata.value.permission == "ai.use"

    def test_yetkisiz_kullanici_hicbir_cagri_yapmaz(self, viewer_ctx, ai_property):
        provider = MockProvider(responses=["olmamali"])
        service = make_service(viewer_ctx, provider)

        with pytest.raises(AuthorizationError):
            service.ask("Merhaba")

        assert provider.calls == []

    def test_yapay_zeka_kapaliyken_anlamli_hata(self, admin_ctx, ai_property):
        provider = MockProvider(responses=["olmamali"])
        service = AIService(
            admin_ctx,
            registry=make_registry(provider, settings=ai_settings(enabled=False)),
        )

        with pytest.raises(ConfigurationError) as hata:
            service.daily_summary()

        assert hata.value.code == "ai_disabled"
        assert "kapalı" in hata.value.user_message
        assert "Ayarlar" in hata.value.context["cozum"]
        assert provider.calls == []
        # Engellenen cagri da iz birakir.
        assert usages(admin_ctx)[0].status is AIUsageStatus.BLOCKED


# ==========================================================================
#  Hata cevirisi
# ==========================================================================
class TestHataCevirisi:
    def test_baglanti_hatasi_turkce_cozum_onerisi_tasir(self, admin_ctx, ai_property):
        service = make_service(
            admin_ctx, MockProvider(fail_with=AIConnectionError(provider="lmstudio"))
        )

        with pytest.raises(AIConnectionError) as hata:
            service.daily_summary()

        assert hata.value.remedy
        assert "LM Studio" in hata.value.remedy
        assert hata.value.user_message.startswith("Yapay zeka")

    def test_zaman_asimi_hatasi_cozum_onerisi_tasir(self, admin_ctx, ai_property):
        service = make_service(
            admin_ctx, MockProvider(fail_with=AITimeoutError(provider="lmstudio"))
        )

        with pytest.raises(AITimeoutError) as hata:
            service.daily_summary()

        assert "zaman aşımı" in hata.value.remedy

    def test_gecersiz_json_anlasilir_hata_uretir(self, admin_ctx, ai_property):
        service = make_service(admin_ctx, MockProvider(responses=["Bu bir JSON degil."]))

        with pytest.raises(AIResponseFormatError) as hata:
            service.classify_review("Oda cok guzeldi.")

        assert hata.value.remedy
        assert "JSON" in hata.value.remedy
        # Cagri yapildi ama gorev basarisiz: kayit FAILED'e cekilir.
        assert usages(admin_ctx)[0].status is AIUsageStatus.FAILED


# ==========================================================================
#  Fiyat onerisi - SALT OKUNUR
# ==========================================================================
class TestFiyatOnerisi:
    def _service(self, ctx) -> AIService:
        cikti = (
            '{"ozet": "Hafta sonu talep yuksek.", "oneriler": ['
            '{"tarih": "2026-09-05", "oda_tipi": "Standart Oda", '
            '"onerilen_fiyat": 1350, "gerekce": "Doluluk %90"}]}'
        )
        return make_service(ctx, MockProvider(responses=[cikti]))

    def test_oneri_uygulanmis_olarak_donmez(self, admin_ctx, ai_property, next_week):
        oneri = self._service(admin_ctx).pricing_suggestion(
            DateRange(next_week, next_week + timedelta(days=7))
        )

        assert oneri.applied is False
        assert oneri.is_advisory is True
        assert oneri.advisory_note == PRICING_ADVISORY_NOTE
        assert oneri.items[0].suggested_rate is not None
        assert oneri.items[0].suggested_rate.amount == Decimal("1350.00")

    def test_oneri_hicbir_fiyati_degistirmez(
        self, admin_ctx, ai_property, sample_room_type, next_week
    ):
        onceki = sample_room_type.base_rate

        self._service(admin_ctx).pricing_suggestion(
            DateRange(next_week, next_week + timedelta(days=7))
        )
        admin_ctx.session.expire_all()

        guncel = admin_ctx.session.scalars(
            select(RoomType).where(RoomType.id == sample_room_type.id)
        ).one()
        assert guncel.base_rate == onceki == Decimal("1000.00")

    def test_applied_alani_disaridan_verilemez(self, admin_ctx, ai_property, next_week):
        """``applied`` ``init=False``: 'uygulanmis oneri' uretmek imkansizdir."""
        oneri = self._service(admin_ctx).pricing_suggestion(
            DateRange(next_week, next_week + timedelta(days=7))
        )
        with pytest.raises((AttributeError, TypeError)):
            oneri.applied = True  # type: ignore[misc]

    def test_degisim_yuzdesi_hesaplanir(self, admin_ctx, ai_property, next_week):
        oneri = self._service(admin_ctx).pricing_suggestion(
            DateRange(next_week, next_week + timedelta(days=7))
        )
        kalem = oneri.items[0]
        assert kalem.current_rate is not None
        assert kalem.change_percent == 35.0


# ==========================================================================
#  Diger gorevler
# ==========================================================================
class TestGorevler:
    def test_doluluk_analizi_calisir(self, admin_ctx, ai_property, next_week):
        provider = MockProvider(responses=["Doluluk yorumu"])
        service = make_service(admin_ctx, provider)

        sonuc = service.occupancy_analysis(DateRange(next_week, next_week + timedelta(days=5)))

        assert sonuc.content == "Doluluk yorumu"
        assert sonuc.task_type is AITaskType.OCCUPANCY_ANALYSIS
        assert find_personal_data(prompt_text(provider)) == []

    def test_mesaj_taslagi_ai_isaretiyle_doner(self, admin_ctx, ai_property):
        service = make_service(admin_ctx, MockProvider(responses=["Sayin misafirimiz, ..."]))

        taslak = service.draft_message(
            DraftKind.RESERVATION_CONFIRMATION, {"oda": "Standart", "gece": 2}
        )

        assert taslak.is_ai_generated is True
        assert AI_GENERATED_MARKER in taslak.marked_text
        assert taslak.kind.label == "Rezervasyon onayi"

    def test_bos_baglamda_taslak_uretilmez(self, admin_ctx, ai_property):
        provider = MockProvider(responses=["olmamali"])
        service = make_service(admin_ctx, provider)

        with pytest.raises(ValidationError):
            service.draft_message(DraftKind.COMPLAINT_RESPONSE, {"durum": "   "})
        assert provider.calls == []

    def test_yorum_analizi_ayristirilir(self, admin_ctx, ai_property):
        cikti = (
            '```json\n{"duygu": "olumsuz", "puan": -0.8, '
            '"kategoriler": ["temizlik", "gurultu"], '
            '"ozet": "Oda kirliydi.", "acil": true}\n```'
        )
        service = make_service(admin_ctx, MockProvider(responses=[cikti]))

        sonuc = service.classify_review("Oda kirliydi ve cok gurultuluydu.")

        assert sonuc.sentiment == "olumsuz"
        assert sonuc.sentiment_level == "danger"
        assert sonuc.score == -0.8
        assert "temizlik" in sonuc.categories
        assert sonuc.is_urgent is True

    def test_serbest_soru_gecmisi_okur_ama_yazmaz(self, admin_ctx, ai_property):
        from app.infrastructure.db.models.ai import AIConversation, AIMessage

        sohbet = AIConversation(user_id=admin_ctx.user_id, title="Test")
        admin_ctx.session.add(sohbet)
        admin_ctx.session.flush()
        admin_ctx.session.add(
            AIMessage(conversation_id=sohbet.id, role="user", content="Onceki soru")
        )
        admin_ctx.session.flush()
        onceki_sayi = len(admin_ctx.session.scalars(select(AIMessage)).all())

        provider = MockProvider(responses=["Yanit"])
        service = make_service(admin_ctx, provider)
        service.ask("Yeni soru", conversation_id=sohbet.id)

        assert "Onceki soru" in prompt_text(provider)
        # Servis salt okunurdur: sohbete yeni mesaj YAZMAZ.
        assert len(admin_ctx.session.scalars(select(AIMessage)).all()) == onceki_sayi

    def test_baskasinin_sohbeti_okunmaz(self, admin_ctx, viewer_ctx, ai_property):
        """Baska bir kullanicinin sohbeti modele TASINMAZ.

        Sohbetler serbest metindir; ham kimlikle sorgulanan bir gecmis,
        yanlis bir numara gecildiginde baskasinin yazdiklarini modele
        gonderirdi.
        """
        from app.infrastructure.db.models.ai import AIConversation, AIMessage

        baskasinin = AIConversation(user_id=viewer_ctx.user_id, title="Baskasinin sohbeti")
        admin_ctx.session.add(baskasinin)
        admin_ctx.session.flush()
        admin_ctx.session.add(
            AIMessage(
                conversation_id=baskasinin.id,
                role="user",
                content="GIZLI-BASKASININ-MESAJI",
            )
        )
        admin_ctx.session.flush()

        provider = MockProvider(responses=["Yanit"])
        service = make_service(admin_ctx, provider)
        service.ask("Yeni soru", conversation_id=baskasinin.id)

        assert "GIZLI-BASKASININ-MESAJI" not in prompt_text(provider)

    def test_bos_soru_reddedilir(self, admin_ctx, ai_property):
        with pytest.raises(ValidationError):
            make_service(admin_ctx).ask("   ")

    def test_secilen_model_isteme_gecer(self, admin_ctx, ai_property):
        provider = MockProvider(responses=["Yanit"])
        service = AIService(
            admin_ctx, registry=make_registry(provider), model="google/gemma-4-12b-qat"
        )

        service.ask("Merhaba")

        assert provider.calls[0].model == "google/gemma-4-12b-qat"
