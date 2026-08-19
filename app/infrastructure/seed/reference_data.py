"""Referans veriler: oda ozellikleri, vergi oranlari, ek hizmetler, departmanlar.

Bu modul **demo verisi degildir**. Buradaki kayitlar gercek bir kurulumda da
ilk acilista olusturulur; isletmenin "klima", "minibar", "On Buro" gibi
tanimlari sifirdan yazmasina gerek kalmaz. Demo verisinden ayri tutulmasinin
somut nedeni :func:`~app.infrastructure.seed.demo_data.clear_demo_data`
davranisidir: demo temizlendiginde bu taban tanimlarin **silinmemesi**
gerekir, aksi halde isletme demo verisini attigi anda oda ozelliklerini de
kaybederdi.

.. warning::
   :data:`TAX_RATES` icindeki oranlar **ornek** degerlerdir ve mevzuatla
   birebir uyumlu olduklari iddia edilmez. KDV ve konaklama vergisi oranlari
   degisebildigi icin gercek oranlar isletme tarafindan
   *Ayarlar > Vergiler* ekranindan girilmelidir. Orani koda gommek, mevzuat
   her degistiginde yazilim guncellemesi gerektirirdi; bu yuzden veritabani
   tablosu tek dogruluk kaynagidir ve buradaki degerler yalnizca bir
   baslangic noktasidir.

Tum ``ensure_*`` fonksiyonlari **idempotent**tir: birden fazla kez cagrilmalari
kayit cogaltmaz, var olanlari bulur ve dondurur. Boylece surum yukseltmesinde
listeye yeni bir satir eklemek yeterlidir; ayrica goc yazmak gerekmez.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.log import get_logger
from app.domain.enums import ChargeType, Currency, ServiceCategory
from app.infrastructure.db.models import Department, RoomFeature, Service, TaxRate

log = get_logger(__name__)


# ==========================================================================
#  Tanim yapilari
# ==========================================================================
@dataclass(frozen=True, slots=True)
class RoomFeatureSpec:
    """Bir oda ozelliginin tanimi."""

    code: str
    name: str
    icon: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class TaxRateSpec:
    """Bir vergi oraninin tanimi.

    ``rate_percent`` degeri ORNEKTIR; bkz. modul basindaki uyari.
    """

    code: str
    name: str
    rate_percent: Decimal
    is_included_in_price: bool = True
    is_default: bool = False
    applies_to_charge_type: ChargeType | None = None


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    """Bir ek hizmetin tanimi."""

    code: str
    name: str
    category: ServiceCategory
    unit_price: Decimal
    tax_rate_percent: Decimal = Decimal("20.00")
    unit: str = "adet"
    is_complimentary: bool = False
    requires_reservation: bool = False
    description: str | None = None


@dataclass(frozen=True, slots=True)
class DepartmentSpec:
    """Bir departmanin tanimi."""

    code: str
    name: str
    description: str | None = None


@dataclass(slots=True)
class ReferenceDataSummary:
    """Referans veri kurulumunun ozeti."""

    room_features_created: int = 0
    tax_rates_created: int = 0
    services_created: int = 0
    departments_created: int = 0

    @property
    def total_created(self) -> int:
        return (
            self.room_features_created
            + self.tax_rates_created
            + self.services_created
            + self.departments_created
        )

    @property
    def any_change(self) -> bool:
        return self.total_created > 0


# ==========================================================================
#  Oda ozellikleri
# ==========================================================================
#: Oda ve oda tipi duzeyinde isaretlenebilen donanim/olanak listesi.
#: ``code`` sistem genelinde benzersizdir; arayuz ikonlari ``icon`` adiyla
#: eslesir (ikon bulunamazsa arayuz sessizce varsayilani kullanir).
ROOM_FEATURES: tuple[RoomFeatureSpec, ...] = (
    RoomFeatureSpec("KLIMA", "Klima", "snowflake", "Bireysel kontrollu klima."),
    RoomFeatureSpec("MINIBAR", "Minibar", "fridge", "Ucretli minibar; tuketim folyoya islenir."),
    RoomFeatureSpec("KASA", "Elektronik Kasa", "lock", "Odada sifreli emanet kasasi."),
    RoomFeatureSpec("BALKON", "Balkon", "balcony"),
    RoomFeatureSpec("DENIZ_MANZARA", "Deniz Manzarasi", "waves"),
    RoomFeatureSpec("JAKUZI", "Jakuzi", "bath"),
    RoomFeatureSpec("WIFI", "Ucretsiz Wi-Fi", "wifi", "Tum tesiste ucretsiz kablosuz internet."),
    RoomFeatureSpec("TV", "LED Televizyon", "tv", "Uydu yayini ve yerel kanallar."),
    RoomFeatureSpec("SAC_KURUTMA", "Sac Kurutma Makinesi", "hairdryer"),
    RoomFeatureSpec("CAY_KAHVE", "Cay-Kahve Seti", "coffee", "Ucretsiz su isiticisi ve set."),
    RoomFeatureSpec("BANYO_KUVET", "Kuvetli Banyo", "bathtub"),
    RoomFeatureSpec("DUSAKABIN", "Dusakabin", "shower"),
    RoomFeatureSpec("CALISMA_MASASI", "Calisma Masasi", "desk"),
    RoomFeatureSpec("UTU_SETI", "Utu ve Utu Masasi", "iron"),
    RoomFeatureSpec("BEBEK_KARYOLA", "Bebek Karyolasi (talep uzerine)", "crib"),
    RoomFeatureSpec("MINI_MUTFAK", "Mini Mutfak", "kitchen"),
    RoomFeatureSpec("ENGELLI_ERISIM", "Engelli Erisimine Uygun", "accessible"),
    RoomFeatureSpec("TERLIK_BORNOZ", "Terlik ve Bornoz", "robe"),
)


# ==========================================================================
#  Vergi oranlari  (ORNEK DEGERLER - bkz. modul basindaki uyari)
# ==========================================================================
#: Baslangic vergi tanimlari. Oranlar ORNEKTIR; isletme kendi durumuna gore
#: gunceller. ``is_included_in_price=True`` Turkiye'deki yaygin ilan bicimini
#: yansitir: oda fiyati vergi dahil duyurulur, vergi fiyatin icinden
#: ayristirilir.
TAX_RATES: tuple[TaxRateSpec, ...] = (
    TaxRateSpec(
        code="KDV10",
        name="KDV %10 - Konaklama (ornek oran)",
        rate_percent=Decimal("10.00"),
        is_included_in_price=True,
        is_default=True,
        applies_to_charge_type=ChargeType.ROOM,
    ),
    TaxRateSpec(
        code="KDV20",
        name="KDV %20 - Hizmet ve Ekstralar (ornek oran)",
        rate_percent=Decimal("20.00"),
        is_included_in_price=True,
        is_default=False,
        applies_to_charge_type=None,
    ),
    TaxRateSpec(
        code="KONAKLAMA2",
        name="Konaklama Vergisi %2 (ornek oran)",
        rate_percent=Decimal("2.00"),
        # Konaklama vergisi faturada ayri satir olarak gosterilir; bu yuzden
        # fiyata dahil degildir.
        is_included_in_price=False,
        is_default=False,
        applies_to_charge_type=ChargeType.CITY_TAX,
    ),
)


# ==========================================================================
#  Ek hizmetler
# ==========================================================================
#: Folyoya islenebilen ucretli/ucretsiz hizmetler. Fiyatlar ornektir.
SERVICES: tuple[ServiceSpec, ...] = (
    ServiceSpec(
        code="SPA_MASAJ",
        name="SPA Masaji (50 dakika)",
        category=ServiceCategory.SPA,
        unit_price=Decimal("1200.00"),
        unit="seans",
        requires_reservation=True,
        description="Randevu ile; SPA merkezinde uygulanir.",
    ),
    ServiceSpec(
        code="TRANSFER",
        name="Havalimani Transferi (tek yon)",
        category=ServiceCategory.TRANSFER,
        unit_price=Decimal("900.00"),
        unit="arac",
        requires_reservation=True,
    ),
    ServiceSpec(
        code="OTOPARK",
        name="Kapali Otopark (gunluk)",
        category=ServiceCategory.PARKING,
        unit_price=Decimal("250.00"),
        unit="gun",
    ),
    ServiceSpec(
        code="CAMASIR",
        name="Camasir Yikama",
        category=ServiceCategory.LAUNDRY,
        unit_price=Decimal("180.00"),
        unit="kg",
    ),
    ServiceSpec(
        code="MINIBAR",
        name="Minibar Tuketimi",
        category=ServiceCategory.MINIBAR,
        unit_price=Decimal("0.00"),
        description="Birim fiyat stok kartindan gelir; bu tanim raporlama icindir.",
    ),
    ServiceSpec(
        code="KAHVALTI",
        name="Acik Bufe Kahvalti (kisi basi)",
        category=ServiceCategory.RESTAURANT,
        unit_price=Decimal("450.00"),
        tax_rate_percent=Decimal("10.00"),
        unit="kisi",
    ),
    ServiceSpec(
        code="GEC_CIKIS",
        name="Gec Cikis (saat basi)",
        category=ServiceCategory.OTHER,
        unit_price=Decimal("300.00"),
        tax_rate_percent=Decimal("10.00"),
        unit="saat",
        description="Musaitlige baglidir; on buro onayi gerekir.",
    ),
)


# ==========================================================================
#  Departmanlar
# ==========================================================================
DEPARTMENTS: tuple[DepartmentSpec, ...] = (
    DepartmentSpec("ONBURO", "On Buro", "Rezervasyon, giris-cikis ve tahsilat."),
    DepartmentSpec("KAT", "Kat Hizmetleri", "Oda temizligi, carsaf ve minibar dolumu."),
    DepartmentSpec("TEKNIK", "Teknik Servis", "Ariza, periyodik bakim ve oda blokeleri."),
    DepartmentSpec("MUHASEBE", "Muhasebe", "Folyo, fatura, tahsilat ve mali raporlar."),
    DepartmentSpec("YIYECEK", "Yiyecek-Icecek", "Restoran, bar ve oda servisi."),
    DepartmentSpec("GUVENLIK", "Guvenlik", "Tesis guvenligi ve kamera izleme."),
)


# ==========================================================================
#  Kurulum fonksiyonlari
# ==========================================================================
def _row_count(session: Session, model: type) -> int:
    """Bir tablodaki satir sayisi - 'kac yeni kayit olustu' hesabi icin."""
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def ensure_room_features(session: Session) -> list[RoomFeature]:
    """Oda ozelliklerini olusturur (varsa dokunmaz) ve tumunu dondurur.

    Oda ozelligi kodu tesisten bagimsiz, sistem genelinde benzersizdir:
    "klima" her tesiste ayni seydir ve zincir otelde tekrar tanimlanmasi
    anlamsiz olurdu.
    """
    existing = {feature.code: feature for feature in session.scalars(select(RoomFeature))}
    result: list[RoomFeature] = []

    for spec in ROOM_FEATURES:
        feature = existing.get(spec.code)
        if feature is None:
            feature = RoomFeature(
                code=spec.code,
                name=spec.name,
                icon=spec.icon,
                description=spec.description,
            )
            session.add(feature)
        result.append(feature)

    session.flush()
    return result


def ensure_tax_rates(session: Session, *, property_id: int) -> list[TaxRate]:
    """Tesise ait ornek vergi oranlarini olusturur ve tumunu dondurur.

    Mevcut bir oranin ``rate_percent`` degeri **guncellenmez**: isletme orani
    elle degistirmisse, surum yukseltmesi bunu ezmemelidir.
    """
    existing = {
        rate.code: rate
        for rate in session.scalars(select(TaxRate).where(TaxRate.property_id == property_id))
    }
    result: list[TaxRate] = []

    for spec in TAX_RATES:
        rate = existing.get(spec.code)
        if rate is None:
            rate = TaxRate(
                property_id=property_id,
                code=spec.code,
                name=spec.name,
                rate_percent=spec.rate_percent,
                is_included_in_price=spec.is_included_in_price,
                is_default=spec.is_default,
                applies_to_charge_type=spec.applies_to_charge_type,
            )
            session.add(rate)
        result.append(rate)

    session.flush()
    return result


def ensure_services(session: Session, *, property_id: int) -> list[Service]:
    """Tesise ait ek hizmet tanimlarini olusturur ve tumunu dondurur."""
    existing = {
        service.code: service
        for service in session.scalars(select(Service).where(Service.property_id == property_id))
    }
    result: list[Service] = []

    for spec in SERVICES:
        service = existing.get(spec.code)
        if service is None:
            service = Service(
                property_id=property_id,
                code=spec.code,
                name=spec.name,
                category=spec.category,
                description=spec.description,
                unit_price=spec.unit_price,
                currency=Currency.TRY,
                tax_rate_percent=spec.tax_rate_percent,
                unit=spec.unit,
                is_complimentary=spec.is_complimentary,
                requires_reservation=spec.requires_reservation,
            )
            session.add(service)
        result.append(service)

    session.flush()
    return result


def ensure_departments(session: Session, *, property_id: int) -> list[Department]:
    """Tesise ait departmanlari olusturur ve tumunu dondurur."""
    existing = {
        department.code: department
        for department in session.scalars(
            select(Department).where(Department.property_id == property_id)
        )
    }
    result: list[Department] = []

    for spec in DEPARTMENTS:
        department = existing.get(spec.code)
        if department is None:
            department = Department(
                property_id=property_id,
                code=spec.code,
                name=spec.name,
                description=spec.description,
            )
            session.add(department)
        result.append(department)

    session.flush()
    return result


def seed_reference_data(
    session: Session,
    *,
    property_id: int,
    commit: bool = True,
) -> ReferenceDataSummary:
    """Tum referans verilerini tek cagrida kurar (idempotent).

    Parameters
    ----------
    property_id:
        Vergi orani, hizmet ve departman kayitlarinin baglanacagi tesis.
    commit:
        ``False`` ise yalnizca ``flush`` yapilir; cagiran taraf islemi kendi
        sinirlari icinde tamamlar. Demo veri ureteci bu sekilde kullanir ve
        boylece tum demo verisi tek bir islemde yazilir.
    """
    summary = ReferenceDataSummary()

    before_features = _row_count(session, RoomFeature)
    ensure_room_features(session)
    summary.room_features_created = _row_count(session, RoomFeature) - before_features

    before_taxes = _row_count(session, TaxRate)
    ensure_tax_rates(session, property_id=property_id)
    summary.tax_rates_created = _row_count(session, TaxRate) - before_taxes

    before_services = _row_count(session, Service)
    ensure_services(session, property_id=property_id)
    summary.services_created = _row_count(session, Service) - before_services

    before_departments = _row_count(session, Department)
    ensure_departments(session, property_id=property_id)
    summary.departments_created = _row_count(session, Department) - before_departments

    if commit:
        session.commit()

    if summary.any_change:
        log.info(
            "referans_verisi_kuruldu",
            oda_ozelligi=summary.room_features_created,
            vergi_orani=summary.tax_rates_created,
            hizmet=summary.services_created,
            departman=summary.departments_created,
        )
    return summary


__all__ = [
    "DEPARTMENTS",
    "ROOM_FEATURES",
    "SERVICES",
    "TAX_RATES",
    "DepartmentSpec",
    "ReferenceDataSummary",
    "RoomFeatureSpec",
    "ServiceSpec",
    "TaxRateSpec",
    "ensure_departments",
    "ensure_room_features",
    "ensure_services",
    "ensure_tax_rates",
    "seed_reference_data",
]
