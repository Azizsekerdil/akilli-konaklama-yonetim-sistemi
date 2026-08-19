"""Demo veri ureteci - sistemin tum ekranlarini dolu ve anlamli gosteren veri kumesi.

======================================================================
GERCEK KISI VERISI KULLANILMAZ - BU DOSYADAKI HER SEY UYDURMADIR
======================================================================
Asagidaki kurallar bilincli olarak uygulanir ve degistirilmemelidir:

* **Adlar**: :data:`FIRST_NAMES` ve :data:`SURNAMES` havuzlarindan rastgele
  eslestirilir. Soyadlari, gercek bir kisiye isaret etmemesi icin dogadan
  turetilmis **uydurma** bilesiklerdir. Uretilen hicbir ad gercek bir kisiyi
  temsil etmez.
* **Kimlik numaralari**: kasten **GECERSIZ** uretilir. T.C. Kimlik No
  dogrulama algoritmasinin **her iki** sagilama hanesi (10. ve 11.) bilerek
  kaydirilir; boylece uretilen dizi hicbir gercek kimlik numarasiyla
  cakisamaz. Bkz. :func:`_fake_identity_number`.
* **E-postalar**: yalnizca ``@ornek-test.local`` alan adinda uretilir.
  ``.local``, RFC 6762 geregi yerel aga ayrilmistir; internete cikan bir
  e-posta bu adrese teslim edilemez. Yanlislikla gercek birine posta
  gonderilmesi bu sayede fiziksel olarak imkansizdir.
* **Telefonlar**: rakam icermeyen, **cevrilemez** bir maske uretilir
  (``+90 5XX XXX XX XX (D041)``). Turkiye'de kurgusal kullanim icin ayrilmis
  bir numara blogu olmadigindan, tam bicimli bir numara uretmek - sentetik
  olsa bile - ekran goruntusu ve sunum yoluyla disari cikabilecek gereksiz
  bir risktir. Bkz. :func:`_demo_phone`.
* **Parolalar**: demo hesap parolalari :data:`DEMO_USERS` icinde acikca
  yazilidir ve donus ozetinde kullaniciya gosterilir. Bunlar **herkese acik**
  demo parolalaridir; gercek bir kurulumda demo verisi silinmeli ve bu
  hesaplar kapatilmalidir.

Belirlenimcilik
---------------
:func:`create_demo_data` ayni ``seed`` degeriyle **ayni veriyi** uretir. Tum
rastgelelik tek bir :class:`random.Random` ornegi uzerinden akar; modul
duzeyinde ``random`` **kullanilmaz**. Tarihler ``date.today()`` referansli
uretildigi icin veri her gun "bugune gore" anlamli kalir; ayni gun icinde
tekrar uretildiginde sonuc birebir aynidir.

Cakisma garantisi
-----------------
Uretilen rezervasyonlarda **hicbir oda ayni gece iki kez satilmaz**. Yerlestirme
:mod:`app.domain.rules.availability` ile dogrulanir. Iptal ve gelmedi kayitlari
da bos araliklara konur: gerceginde bu odalar yeniden satilabilirdi, ancak demo
veride hangi durum filtresiyle bakilirsa bakilsin cakisma gorunmemesi
raporlarin ve testlerin yorumunu kolaylastirir.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Final

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, ValidationError
from app.core.log import get_logger
from app.domain.enums import (
    AuditAction,
    BedType,
    ChargeType,
    ConsentType,
    Currency,
    EmploymentStatus,
    FolioStatus,
    GuestRelation,
    GuestTitle,
    HousekeepingStatus,
    HousekeepingTaskType,
    IdentityDocumentType,
    InvoiceStatus,
    LostItemStatus,
    MaintenanceCategory,
    MaintenanceStatus,
    MealPlan,
    NotificationType,
    PaymentMethod,
    PaymentStatus,
    Priority,
    PropertyType,
    PurchaseRequestStatus,
    RatePlanType,
    ReservationSource,
    ReservationStatus,
    RoomHousekeepingStatus,
    RoomOccupancyStatus,
    RoomView,
    ShiftType,
    StayStatus,
    StockMovementType,
    TransactionDirection,
    VIPLevel,
)
from app.domain.rules.availability import Booking, RoomBlock, is_room_available
from app.domain.rules.pricing import RateRule, calculate_stay_price
from app.domain.value_objects import DateRange
from app.infrastructure.db.models import (
    Agency,
    AuditLog,
    Building,
    CashRegisterEntry,
    Charge,
    Company,
    ConsentRecord,
    Department,
    Document,
    Employee,
    Floor,
    Folio,
    Guest,
    GuestNote,
    GuestPreference,
    HousekeepingTask,
    InventoryItem,
    Invoice,
    InvoiceLine,
    LostAndFoundItem,
    MaintenancePart,
    MaintenanceTicket,
    MinibarConsumption,
    Notification,
    Payment,
    Property,
    PurchaseRequest,
    PurchaseRequestLine,
    RatePlan,
    RatePlanRate,
    Reservation,
    ReservationGuest,
    ReservationRoom,
    Role,
    Room,
    RoomFeature,
    RoomPhoto,
    RoomType,
    Service,
    Setting,
    Shift,
    Stay,
    StockMovement,
    Supplier,
    TaxRate,
    User,
    UserSession,
    WaitlistEntry,
    Warehouse,
)
from app.infrastructure.seed.reference_data import seed_reference_data
from app.security.bootstrap import bootstrap_security
from app.security.passwords import hash_password

log = get_logger(__name__)


# ==========================================================================
#  Demo isaretleri
# ==========================================================================
#: Demo tesisinin kodu. Tesise bagli her sey (oda, rezervasyon, folyo, stok...)
#: bu kayit uzerinden bulunur; temizleme islemi de buradan yurur.
DEMO_PROPERTY_CODE: Final = "DEMO01"

#: Tesise bagli **olmayan** kayitlarda (misafir, kullanici) demo isareti.
#: ``notes`` alanina yazilir; boylece isletmenin kendi girdigi kayitlar
#: temizlemeden etkilenmez.
DEMO_MARKER: Final = "[DEMO VERISI]"

#: Kurumsal musteri, acente ve tedarikci kodlarinin on eki.
DEMO_CODE_PREFIX: Final = "DEMO-"

#: Demo e-postalarinin alan adi. ``.local`` internete cikmaz (RFC 6762).
DEMO_EMAIL_DOMAIN: Final = "ornek-test.local"

DEMO_WARNING: Final = (
    "UYARI: Bu veri kumesi tamamen uydurmadir ve yalnizca tanitim/deneme "
    "amaclidir. Icindeki kisi adlari, kimlik numaralari, e-posta adresleri ve "
    "telefon numaralari gercek hicbir kisiye ait degildir; kimlik numaralari "
    "kasten gecersiz uretilmistir. Asagidaki demo parolalari herkese aciktir - "
    "gercek bir kurulumda once demo verisini silin, sonra bu hesaplari kapatin."
)


# ==========================================================================
#  Uydurma ad havuzlari
# ==========================================================================
#: Yaygin Turkce on adlar. Tek baslarina bir kisiyi isaret etmezler.
FIRST_NAMES: Final[tuple[str, ...]] = (
    "Aylin",
    "Berk",
    "Ceren",
    "Deniz",
    "Ece",
    "Firat",
    "Gizem",
    "Hakan",
    "Irem",
    "Kaan",
    "Lale",
    "Merve",
    "Nazli",
    "Onur",
    "Pinar",
    "Ruya",
    "Selin",
    "Tolga",
    "Umut",
    "Yasemin",
    "Zeynep",
    "Baris",
    "Cem",
    "Dilek",
    "Efe",
    "Gonca",
    "Hazal",
    "Ilker",
    "Kerem",
    "Melis",
    "Nehir",
    "Ozan",
    "Sinan",
    "Tugce",
    "Volkan",
    "Yigit",
    "Sena",
    "Burak",
    "Elif",
    "Mert",
)

#: **Uydurma** soyadlari: doga/nesne sozcuklerinden turetilmis bilesikler.
#: Gercek soy isim listelerinden secilmemistir; amac, ad-soyad ciftinin
#: gercek bir kisiye denk gelme olasiligini en aza indirmektir.
SURNAMES: Final[tuple[str, ...]] = (
    "Yildizli",
    "Gunesli",
    "Bulutlu",
    "Yagmurlu",
    "Ruzgarli",
    "Cicekli",
    "Zeytinli",
    "Findikli",
    "Kumsalli",
    "Mercanli",
    "Yelkenli",
    "Fenerli",
    "Kervanli",
    "Ipekli",
    "Selvili",
    "Lalezar",
    "Menekseli",
    "Karanfilli",
    "Sumbullu",
    "Denizcan",
    "Aydinlik",
    "Gokkusakli",
    "Sabahci",
    "Aksamci",
    "Dagliyol",
    "Ovalik",
    "Cinarli",
    "Zambakli",
    "Nergisli",
    "Papatyali",
)

#: Uyruk dagilimi - cogunluk yerli, bir kismi yabanci misafir.
NATIONALITIES: Final[tuple[tuple[str, str], ...]] = (
    ("Turkiye", "tr"),
    ("Turkiye", "tr"),
    ("Turkiye", "tr"),
    ("Turkiye", "tr"),
    ("Almanya", "de"),
    ("Rusya", "ru"),
    ("Ingiltere", "en"),
    ("Hollanda", "en"),
)


# ==========================================================================
#  Olcek profilleri
# ==========================================================================
@dataclass(frozen=True, slots=True)
class ScaleProfile:
    """Uretilecek kayit adetleri.

    Olcek buyudukce yalnizca adetler artar; veri kurgusu (dagilimlar, durum
    karisimlari) ayni kalir. Boylece kucuk olcek testlerde hizli, buyuk olcek
    performans denemelerinde gercekci olur.
    """

    name: str
    rooms: int
    guests: int
    reservations: int
    housekeeping_tasks: int
    maintenance_tickets: int
    inventory_items: int


SCALE_PROFILES: Final[dict[str, ScaleProfile]] = {
    "small": ScaleProfile(
        name="small",
        rooms=14,
        guests=24,
        reservations=30,
        housekeeping_tasks=10,
        maintenance_tickets=5,
        inventory_items=14,
    ),
    "medium": ScaleProfile(
        name="medium",
        rooms=40,
        guests=60,
        reservations=80,
        housekeeping_tasks=25,
        maintenance_tickets=10,
        inventory_items=30,
    ),
    "large": ScaleProfile(
        name="large",
        rooms=96,
        guests=150,
        reservations=220,
        housekeeping_tasks=60,
        maintenance_tickets=24,
        inventory_items=60,
    ),
}


# ==========================================================================
#  Demo kullanicilari
# ==========================================================================
@dataclass(frozen=True, slots=True)
class DemoUserSpec:
    """Bir demo kullanicisinin ve bagli calisan kaydinin tanimi."""

    username: str
    first_name: str
    last_name: str
    role_code: str
    department_code: str
    position: str
    password: str


#: Demo hesaplari. Parolalar bilincli olarak sabittir ve ozette gosterilir;
#: demo verisi zaten herkese acik ornek veridir, gizlenecek bir sey yoktur.
DEMO_USERS: Final[tuple[DemoUserSpec, ...]] = (
    DemoUserSpec(
        "demo.mudur", "Selin", "Yildizli", "manager", "ONBURO", "Otel Muduru", "DemoMudur2026!"
    ),
    DemoUserSpec(
        "demo.onburo",
        "Kerem",
        "Gunesli",
        "frontdesk",
        "ONBURO",
        "On Buro Gorevlisi",
        "DemoOnburo2026!",
    ),
    DemoUserSpec(
        "demo.kat",
        "Nazli",
        "Bulutlu",
        "housekeeping",
        "KAT",
        "Kat Hizmetleri Sefi",
        "DemoKat2026!",
    ),
    DemoUserSpec(
        "demo.teknik",
        "Onur",
        "Ruzgarli",
        "maintenance",
        "TEKNIK",
        "Teknik Servis Sorumlusu",
        "DemoTeknik2026!",
    ),
    DemoUserSpec(
        "demo.muhasebe",
        "Merve",
        "Zeytinli",
        "accounting",
        "MUHASEBE",
        "Muhasebe Uzmani",
        "DemoMuhasebe2026!",
    ),
)

#: Kullanici hesabi **olmayan** ek calisanlar. Otelde herkesin sisteme girisi
#: olmaz (bkz. ``Employee`` docstring); kat gorevlileri gorev listelerinde
#: gorunur ama uygulamaya girmez. Gorev dagitimi bunlar olmadan gercekci
#: durmazdi.
EXTRA_EMPLOYEES: Final[tuple[tuple[str, str, str, str], ...]] = (
    ("Hazal", "Cicekli", "KAT", "Kat Gorevlisi"),
    ("Efe", "Findikli", "KAT", "Kat Gorevlisi"),
    ("Sena", "Mercanli", "KAT", "Kat Gorevlisi"),
)


# ==========================================================================
#  Ozet yapilari
# ==========================================================================
@dataclass(frozen=True, slots=True)
class DemoUserCredential:
    """Demo kullanicisinin arayuzde gosterilecek giris bilgisi."""

    username: str
    password: str
    role_code: str
    full_name: str

    def format(self) -> str:
        return f"{self.username} / {self.password}  ({self.full_name} - {self.role_code})"


@dataclass(slots=True)
class DemoDataSummary:
    """Uretilen demo verisinin ozeti.

    Kurulum sihirbazi ve CLI bu ozeti kullaniciya gosterir. ``users`` alani
    demo parolalarini icerir; :data:`DEMO_WARNING` ile birlikte gosterilmelidir.
    """

    seed: int
    scale: str
    reference_date: date
    counts: dict[str, int] = field(default_factory=dict)
    users: list[DemoUserCredential] = field(default_factory=list)
    warning: str = DEMO_WARNING

    @property
    def total_records(self) -> int:
        """Uretilen toplam kayit sayisi."""
        return sum(self.counts.values())

    def format_report(self) -> str:
        """Ekranda/gunlukte gosterilecek Turkce ozet metni."""
        lines = [
            f"Demo veri olusturuldu (olcek: {self.scale}, seed: {self.seed}).",
            f"Referans tarih: {self.reference_date.strftime('%d.%m.%Y')}",
            f"Toplam kayit: {self.total_records}",
            "",
            "Kayit dagilimi:",
        ]
        lines.extend(f"  - {name}: {count}" for name, count in sorted(self.counts.items()) if count)
        lines.extend(["", "Demo kullanicilari (parolalar DEMO amaclidir):"])
        lines.extend(f"  - {credential.format()}" for credential in self.users)
        lines.extend(["", self.warning])
        return "\n".join(lines)


@dataclass(slots=True)
class DemoClearSummary:
    """Silinen demo kayitlarinin ozeti."""

    deleted: dict[str, int] = field(default_factory=dict)

    @property
    def total_deleted(self) -> int:
        return sum(self.deleted.values())

    @property
    def any_deleted(self) -> bool:
        return self.total_deleted > 0


# ==========================================================================
#  Kucuk yardimcilar
# ==========================================================================
def _at(day: date, hour: int, minute: int = 0) -> datetime:
    """Gun + saat -> zaman dilimi bilincli (UTC) zaman damgasi.

    Naive ``datetime`` uretmek TZDateTime sutunlariyla karsilastirmalarda
    calisma aninda ``TypeError`` uretirdi; bu yuzden tzinfo her zaman verilir.
    """
    return datetime.combine(day, time(hour, minute), tzinfo=UTC)


def _split_count(total: int, weights: Sequence[tuple[str, float]]) -> dict[str, int]:
    """Toplami agirliklara gore tam sayilara boler; toplam **korunur**.

    Basit ``int(total * w)`` yaklasimi asagi yuvarlama nedeniyle toplami
    kaybederdi (or. 30 rezervasyon isteyip 27 uretmek). En buyuk kalan
    yontemi kullanilir; esitlikte anahtar sirasi belirleyicidir, boylece
    sonuc belirlenimcidir.

    >>> _split_count(10, [("a", 1.0), ("b", 1.0), ("c", 1.0)])
    {'a': 4, 'b': 3, 'c': 3}
    """
    result = {key: 0 for key, _ in weights}
    if total <= 0 or not weights:
        return result

    weight_sum = sum(weight for _, weight in weights) or 1.0
    exact = [(key, total * weight / weight_sum) for key, weight in weights]
    for key, value in exact:
        result[key] = int(value)

    remainder = total - sum(result.values())
    order = sorted(
        range(len(exact)),
        key=lambda index: (-(exact[index][1] - int(exact[index][1])), index),
    )
    for index in order[:remainder]:
        result[exact[index][0]] += 1
    return result


def _fake_identity_number(rng: random.Random) -> str:
    """Kasten **GECERSIZ** 11 haneli bir kimlik numarasi uretir.

    T.C. Kimlik No dogrulamasi iki sagilama kullanir::

        d10 = ((d1+d3+d5+d7+d9) * 7 - (d2+d4+d6+d8)) mod 10
        d11 = (d1+...+d10) mod 10

    Burada **ikisi de bilerek kaydirilir**. Sonuc: uretilen dizi hicbir
    dogrulayicidan gecemez, dolayisiyla gercek bir kimlik numarasiyla
    cakisma ihtimali yoktur. Demo veride gecerli numara uretmek, o numaranin
    bir gun gercek bir kisiye ait cikmasi riskini dogururdu.
    """
    digits = [rng.randint(1, 9)] + [rng.randint(0, 9) for _ in range(8)]
    tenth = (sum(digits[0:9:2]) * 7 - sum(digits[1:8:2])) % 10
    broken_tenth = (tenth + 5) % 10
    eleventh = (sum(digits) + broken_tenth) % 10
    broken_eleventh = (eleventh + 3) % 10
    return "".join(str(digit) for digit in digits) + f"{broken_tenth}{broken_eleventh}"


def _fake_passport_number(rng: random.Random) -> str:
    """Uydurma pasaport numarasi - iki harf + yedi rakam."""
    letters = "".join(rng.choice("ABCDEFGHJKLMNPRSTUVYZ") for _ in range(2))
    return letters + "".join(str(rng.randint(0, 9)) for _ in range(7))


#: Demo telefon numaralarinin maskeli govdesi. Rakam **icermez**, bu yuzden
#: hicbir sebekede cevrilemez.
DEMO_PHONE_MASK: Final = "+90 5XX XXX XX XX"


def _demo_phone(index: int) -> str:
    """Maskeli, **cevrilemez** demo telefon numarasi uretir.

    Ornek: ``+90 5XX XXX XX XX (D041)``

    Neden tam bicimli numara uretilmiyor?
    -------------------------------------
    Onceki surum ``+90 555 000 XX XX`` bicimli, **12 haneli ve bicim olarak
    cevrilebilir** numaralar uretiyordu. Bu numaralar demo verinin kendisinde
    kalsaydi sorun kucuk olurdu; ancak ekran goruntusu alma betigi
    (``sunum/ekran_yakala.py``) bu veriyi yakalayip tanitim sunumuna
    gomuyordu. Turkiye'de kurgusal kullanim icin **ayrilmis bir numara blogu
    yoktur**; ``555`` gercek bir mobil onektir. Genis dagitilan bir PDF'te
    cevrilebilir bicimde numara yayimlamak, numaralar sentetik olsa bile
    gereksiz bir risktir.

    Cozum: rakamlar ``X`` ile degistirilir. Satirlar birbirinden ayirt
    edilebilsin diye sona ``(D<indeks>)`` biciminde, telefon numarasi
    olmadigi acikca gorulen bir demo etiketi eklenir.

    >>> _demo_phone(41)
    '+90 5XX XXX XX XX (D041)'
    >>> any(ch.isdigit() for ch in _demo_phone(41).split("(")[0])
    False
    """
    return f"{DEMO_PHONE_MASK} (D{index % 1000:03d})"


def _demo_email(first_name: str, last_name: str, index: int) -> str:
    """``ad.soyad###@ornek-test.local`` bicimli, teslim edilemez adres."""
    return f"{first_name.lower()}.{last_name.lower()}{index:03d}@{DEMO_EMAIL_DOMAIN}"


def _money(value: Decimal | int | str) -> Decimal:
    """Kurus hassasiyetine yuvarlanmis ``Decimal`` - para icin float YASAK.

    Imza bilincli olarak ``float`` kabul **etmez**. Kabul etseydi cagiran taraf
    ``_money(rng.uniform(...))`` yazmakta serbest olurdu; ara deger yine float
    olur ve "para yolunda float yok" kurali kagit uzerinde kalirdi. Rastgele
    tutar gerektiginde :func:`_random_money` kullanilir.
    """
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _random_money(rng: random.Random, low: str, high: str) -> Decimal:
    """``[low, high]`` araliginda rastgele tutar - cekilis **kurus** uzerinden.

    ``rng.uniform`` float dondururdu. Deger sonunda ``Decimal``e cevrilse bile
    ara adimda ikilik kayan nokta gosterimi devreye girerdi; bu modulun kurali
    para yolunda float bulundurmamaktir. Cekilis dogrudan kurus tam sayisi
    uzerinde yapildigi icin sonuc her zaman tam olarak iki ondalikli olur.
    """
    low_kurus = int(_money(low) * 100)
    high_kurus = int(_money(high) * 100)
    return _money(Decimal(rng.randint(low_kurus, high_kurus)) / Decimal(100))


# ==========================================================================
#  Uretici
# ==========================================================================
class _DemoBuilder:
    """Demo veri uretiminin durumunu tasiyan yardimci.

    Uretim adimlari birbirine bagimlidir (odalar olmadan rezervasyon,
    rezervasyon olmadan folyo uretilemez). Bu durumu fonksiyonlar arasi
    dolastirmak yerine tek bir nesnede toplamak, adim sirasini ve bagimliligi
    okunur kilar.
    """

    def __init__(self, session: Session, *, rng: random.Random, profile: ScaleProfile) -> None:
        self.session = session
        self.rng = rng
        self.profile = profile
        # Isletme gunu yerel takvim gunudur; UTC degil. Misafir "bugun giris
        # yapiyorum" derken kendi takvimini kasteder.
        self.today: date = date.today()  # noqa: DTZ011
        self.counts: dict[str, int] = {}

        self.hotel_property: Property
        self.buildings: list[Building] = []
        self.floors: list[Floor] = []
        self.departments: dict[str, Department] = {}
        self.features: dict[str, RoomFeature] = {}
        self.services: dict[str, Service] = {}
        self.tax_rates: dict[str, TaxRate] = {}
        self.room_types: dict[str, RoomType] = {}
        self.rooms: list[Room] = []
        self.rate_plans: list[RatePlan] = []
        self.rate_rules: dict[tuple[int, int], list[RateRule]] = {}
        self.employees: list[Employee] = []
        self.users: dict[str, User] = {}
        self.credentials: list[DemoUserCredential] = []
        self.companies: list[Company] = []
        self.agencies: list[Agency] = []
        self.suppliers: list[Supplier] = []
        self.guests: list[Guest] = []
        self.warehouses: list[Warehouse] = []
        self.inventory_items: list[InventoryItem] = []
        self.reservations: list[Reservation] = []
        self.stays: list[Stay] = []
        self.folios: list[Folio] = []

        #: Yerlestirilmis oda dolulugu - cakisma kontrolunun girdisi.
        self._bookings: list[Booking] = []
        #: Bakim/ariza nedeniyle satisa kapali donemler.
        self._blocks: list[RoomBlock] = []
        self._used_identities: set[str] = set()
        self._sequence = 0

    # ---------------- sayaclar ----------------
    def _bump(self, key: str, amount: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + amount

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    # ================================================================
    #  1. Tesis, bina, kat
    # ================================================================
    def create_property(self) -> None:
        self.hotel_property = Property(
            code=DEMO_PROPERTY_CODE,
            name="Demo Sahil Oteli",
            property_type=PropertyType.HOTEL,
            star_rating=4,
            address_line="Ornek Sahil Caddesi No: 1",
            district="Konyaalti",
            city="Antalya",
            postal_code="07070",
            country="Turkiye",
            phone=f"{DEMO_PHONE_MASK} (D900)",
            email=f"iletisim@{DEMO_EMAIL_DOMAIN}",
            website=f"https://{DEMO_EMAIL_DOMAIN}",
            tax_office="Ornek Vergi Dairesi",
            tax_number="0000000001",
            default_currency=Currency.TRY,
            check_in_time=time(14, 0),
            check_out_time=time(12, 0),
            notes=DEMO_MARKER,
        )
        self.session.add(self.hotel_property)
        self.session.flush()
        self._bump("property")

        building_specs = (
            ("A", "Ana Bina", "Resepsiyon, restoran ve toplanti salonlari bu binadadir.", 3),
            ("B", "Deniz Blok", "Denize bakan, sezonluk acilan ikinci blok.", 2),
        )
        for code, name, description, floor_count in building_specs:
            building = Building(
                property_id=self.hotel_property.id,
                code=code,
                name=name,
                description=description,
            )
            self.session.add(building)
            self.session.flush()
            self.buildings.append(building)
            self._bump("building")

            for number in range(1, floor_count + 1):
                floor = Floor(
                    building_id=building.id,
                    number=number,
                    name=f"{number}. Kat",
                )
                self.session.add(floor)
                self.floors.append(floor)
                self._bump("floor")
        self.session.flush()

    # ================================================================
    #  2. Referans veriler
    # ================================================================
    def create_reference_data(self) -> None:
        summary = seed_reference_data(
            self.session, property_id=self.hotel_property.id, commit=False
        )
        self._bump("room_feature", summary.room_features_created)
        self._bump("tax_rate", summary.tax_rates_created)
        self._bump("service", summary.services_created)
        self._bump("department", summary.departments_created)

        self.features = {
            feature.code: feature for feature in self.session.scalars(select(RoomFeature))
        }
        self.services = {
            service.code: service
            for service in self.session.scalars(
                select(Service).where(Service.property_id == self.hotel_property.id)
            )
        }
        self.tax_rates = {
            rate.code: rate
            for rate in self.session.scalars(
                select(TaxRate).where(TaxRate.property_id == self.hotel_property.id)
            )
        }
        self.departments = {
            department.code: department
            for department in self.session.scalars(
                select(Department).where(Department.property_id == self.hotel_property.id)
            )
        }

    # ================================================================
    #  3. Oda tipleri ve odalar
    # ================================================================
    def create_room_types(self) -> None:
        specs = (
            {
                "code": "STD",
                "name": "Standart Oda",
                "description": "22 m2, cift kisilik yatak, sehir veya bahce manzarasi.",
                "base_occupancy": 2,
                "max_occupancy": 3,
                "max_adults": 3,
                "max_children": 1,
                "bed_type": BedType.DOUBLE,
                "bed_count": 1,
                "size_sqm": 22,
                "base_rate": _money("1000.00"),
                "extra_adult_rate": _money("250.00"),
                "extra_child_rate": _money("125.00"),
                "features": ("KLIMA", "TV", "WIFI", "SAC_KURUTMA", "DUSAKABIN", "KASA"),
            },
            {
                "code": "DLX",
                "name": "Deluxe Oda",
                "description": "30 m2, king yatak, balkon ve oturma kosesi.",
                "base_occupancy": 2,
                "max_occupancy": 3,
                "max_adults": 3,
                "max_children": 1,
                "bed_type": BedType.KING,
                "bed_count": 1,
                "size_sqm": 30,
                "base_rate": _money("1500.00"),
                "extra_adult_rate": _money("350.00"),
                "extra_child_rate": _money("175.00"),
                "features": (
                    "KLIMA",
                    "TV",
                    "WIFI",
                    "SAC_KURUTMA",
                    "BANYO_KUVET",
                    "KASA",
                    "MINIBAR",
                    "BALKON",
                    "CAY_KAHVE",
                ),
            },
            {
                "code": "AILE",
                "name": "Aile Odasi",
                "description": "42 m2, iki ayri bolum, cocuklu aileler icin.",
                "base_occupancy": 3,
                "max_occupancy": 5,
                "max_adults": 4,
                "max_children": 3,
                "bed_type": BedType.DOUBLE,
                "bed_count": 2,
                "size_sqm": 42,
                "base_rate": _money("2200.00"),
                "extra_adult_rate": _money("400.00"),
                "extra_child_rate": _money("200.00"),
                "features": (
                    "KLIMA",
                    "TV",
                    "WIFI",
                    "SAC_KURUTMA",
                    "BANYO_KUVET",
                    "KASA",
                    "MINIBAR",
                    "BALKON",
                    "CAY_KAHVE",
                    "BEBEK_KARYOLA",
                ),
            },
            {
                "code": "SUIT",
                "name": "Suit",
                "description": "55 m2, ayri salon, jakuzi ve genis deniz manzarali teras.",
                "base_occupancy": 2,
                "max_occupancy": 4,
                "max_adults": 4,
                "max_children": 2,
                "bed_type": BedType.KING,
                "bed_count": 1,
                "size_sqm": 55,
                "base_rate": _money("3500.00"),
                "extra_adult_rate": _money("600.00"),
                "extra_child_rate": _money("300.00"),
                "features": (
                    "KLIMA",
                    "TV",
                    "WIFI",
                    "SAC_KURUTMA",
                    "BANYO_KUVET",
                    "JAKUZI",
                    "KASA",
                    "MINIBAR",
                    "BALKON",
                    "CAY_KAHVE",
                    "MINI_MUTFAK",
                    "TERLIK_BORNOZ",
                ),
            },
        )

        for spec in specs:
            feature_codes: tuple[str, ...] = spec.pop("features")  # type: ignore[assignment]
            room_type = RoomType(
                property_id=self.hotel_property.id,
                notes=DEMO_MARKER,
                **spec,  # type: ignore[arg-type]
            )
            room_type.features = [
                self.features[code] for code in feature_codes if code in self.features
            ]
            self.session.add(room_type)
            self.room_types[str(spec["code"])] = room_type
            self._bump("room_type")
        self.session.flush()

    def create_rooms(self) -> None:
        """Odalari tipler arasinda dagitarak ve katlara yayarak olusturur."""
        distribution = _split_count(
            self.profile.rooms,
            [("STD", 45.0), ("DLX", 30.0), ("AILE", 15.0), ("SUIT", 10.0)],
        )
        plan: list[str] = []
        for code, count in distribution.items():
            plan.extend([code] * count)
        self.rng.shuffle(plan)

        # Odalar katlara sirayla dagitilir; her katta en fazla ceil(n/kat)
        # oda olur. Boylece kat plani ekrani dengeli gorunur.
        floor_count = len(self.floors) or 1
        per_floor = -(-len(plan) // floor_count)

        index = 0
        for floor in self.floors:
            building = next(b for b in self.buildings if b.id == floor.building_id)
            for slot in range(per_floor):
                if index >= len(plan):
                    break
                type_code = plan[index]
                index += 1
                prefix = "" if building.code == "A" else building.code
                number = f"{prefix}{floor.number}{slot + 1:02d}"

                if building.code == "B":
                    view = RoomView.SEA
                elif type_code == "SUIT":
                    view = RoomView.POOL
                else:
                    view = self.rng.choice([RoomView.GARDEN, RoomView.CITY, RoomView.POOL])

                room = Room(
                    property_id=self.hotel_property.id,
                    room_type_id=self.room_types[type_code].id,
                    floor_id=floor.id,
                    number=number,
                    view=view,
                    housekeeping_status=RoomHousekeepingStatus.CLEAN,
                    occupancy_status=RoomOccupancyStatus.VACANT,
                    is_smoking=False,
                    is_accessible=(floor.number == 1 and slot == 0),
                    notes=DEMO_MARKER,
                )
                self.session.add(room)
                self.rooms.append(room)
                self._bump("room")
        self.session.flush()

        self._setup_blocked_rooms()

    def _setup_blocked_rooms(self) -> None:
        """Satisa kapali odalari **rezervasyonlardan once** belirler.

        Sira onemlidir: blok once konursa, cakisma kontrolu o odaya rezervasyon
        yerlestirmez. Tersi durumda "arizali odada misafir var" gibi tutarsiz
        bir demo verisi olusurdu.
        """
        if len(self.rooms) < 3:
            return

        # 1) Ariza nedeniyle gecici olarak kapali oda (bakim kaydi buna baglanir).
        blocked = self.rooms[-1]
        blocked.housekeeping_status = RoomHousekeepingStatus.OUT_OF_ORDER
        blocked.out_of_service_from = self.today
        blocked.out_of_service_until = self.today + timedelta(days=3)
        blocked.out_of_service_reason = "Klima motoru arizali - parca bekleniyor."
        self._blocks.append(
            RoomBlock(
                room_id=blocked.id,
                date_range=DateRange(self.today, self.today + timedelta(days=4)),
                reason=blocked.out_of_service_reason,
            )
        )

        # 2) Suresiz servis disi oda (tadilat). Tarih araligi verilmez -> hicbir
        #    tarihte satilamaz.
        out_of_service = self.rooms[-2]
        out_of_service.housekeeping_status = RoomHousekeepingStatus.OUT_OF_SERVICE
        out_of_service.out_of_service_reason = "Banyo yenileme calismasi suruyor."
        self._blocks.append(
            RoomBlock(
                room_id=out_of_service.id,
                date_range=None,
                reason=out_of_service.out_of_service_reason,
            )
        )

    # ================================================================
    #  4. Fiyat planlari ve sezonluk fiyatlar
    # ================================================================
    def create_rate_plans(self) -> None:
        """Uc fiyat plani ve her biri icin sezonluk/hafta sonu fiyat satirlari.

        Sezonlar bugune goredir; boylece demo veri her zaman "icinde
        bulunulan sezonu" gosterir. Hafta sonu farki ayri satirlarla
        verilir: hafta ici maskesi (Pzt-Per + Paz) ile hafta sonu maskesi
        (Cum-Cmt) **kesismez**, bu yuzden her gun icin tam olarak bir satir
        gecerlidir ve fiyat secimi belirsiz kalmaz.
        """
        plan_specs = (
            {
                "code": "STD",
                "name": "Standart Tarife",
                "description": "Esnek iptal kosullu, herkese acik temel tarife.",
                "plan_type": RatePlanType.STANDARD,
                "meal_plan": MealPlan.BED_BREAKFAST,
                "is_refundable": True,
                "free_cancellation_hours": 24,
                "cancellation_fee_percent": _money("50.00"),
                "min_advance_days": 0,
                "priority": 0,
                "factor": Decimal("1.00"),
            },
            {
                "code": "ERKEN",
                "name": "Erken Rezervasyon (-%15)",
                "description": "Girise en az 30 gun kala yapilan rezervasyonlar icin.",
                "plan_type": RatePlanType.EARLY_BIRD,
                "meal_plan": MealPlan.HALF_BOARD,
                "is_refundable": True,
                "free_cancellation_hours": 72,
                "cancellation_fee_percent": _money("25.00"),
                "min_advance_days": 30,
                "priority": 10,
                "factor": Decimal("0.85"),
            },
            {
                "code": "IADESIZ",
                "name": "Iade Edilemez (-%10)",
                "description": "Pesin odemeli, iptal ve degisiklik hakki yoktur.",
                "plan_type": RatePlanType.NON_REFUNDABLE,
                "meal_plan": MealPlan.BED_BREAKFAST,
                "is_refundable": False,
                "free_cancellation_hours": 0,
                "cancellation_fee_percent": _money("100.00"),
                "min_advance_days": 0,
                "priority": 5,
                "factor": Decimal("0.90"),
            },
        )

        seasons = (
            (
                "Dusuk Sezon",
                self.today - timedelta(days=180),
                self.today - timedelta(days=61),
                Decimal("0.80"),
            ),
            (
                "Orta Sezon",
                self.today - timedelta(days=60),
                self.today + timedelta(days=29),
                Decimal("1.00"),
            ),
            (
                "Yuksek Sezon",
                self.today + timedelta(days=30),
                self.today + timedelta(days=180),
                Decimal("1.35"),
            ),
        )
        # bit 0 = Pazartesi ... bit 6 = Pazar
        weekday_mask = 0b1001111  # Pzt, Sal, Car, Per, Paz
        weekend_mask = 0b0110000  # Cum, Cmt
        weekend_factor = Decimal("1.15")

        for spec in plan_specs:
            factor: Decimal = spec.pop("factor")  # type: ignore[assignment]
            plan = RatePlan(
                property_id=self.hotel_property.id,
                currency=Currency.TRY,
                min_nights=1,
                no_show_fee_percent=_money("100.00"),
                valid_from=self.today - timedelta(days=365),
                valid_to=self.today + timedelta(days=365),
                notes=DEMO_MARKER,
                **spec,  # type: ignore[arg-type]
            )
            self.session.add(plan)
            self.session.flush()
            self.rate_plans.append(plan)
            self._bump("rate_plan")

            for room_type in self.room_types.values():
                rules: list[RateRule] = []
                for season_name, start, end, season_factor in seasons:
                    for mask, mask_factor in (
                        (weekday_mask, Decimal("1.00")),
                        (weekend_mask, weekend_factor),
                    ):
                        amount = _money(room_type.base_rate * factor * season_factor * mask_factor)
                        label = (
                            season_name if mask == weekday_mask else f"{season_name} - Hafta Sonu"
                        )
                        self.session.add(
                            RatePlanRate(
                                rate_plan_id=plan.id,
                                room_type_id=room_type.id,
                                valid_from=start,
                                valid_to=end,
                                amount=amount,
                                weekday_mask=mask,
                                season_name=label,
                            )
                        )
                        rules.append(
                            RateRule(
                                amount=amount,
                                valid_from=start,
                                valid_to=end,
                                weekday_mask=mask,
                                season_name=label,
                                rate_plan_code=plan.code,
                            )
                        )
                        self._bump("rate_plan_rate")
                self.rate_rules[(plan.id, room_type.id)] = rules
        self.session.flush()

    # ================================================================
    #  5. Personel ve kullanicilar
    # ================================================================
    def create_staff(self) -> None:
        roles = {role.code: role for role in self.session.scalars(select(Role))}
        hire_base = self.today - timedelta(days=900)

        for index, spec in enumerate(DEMO_USERS):
            role = roles.get(spec.role_code)
            user = User(
                username=spec.username,
                email=_demo_email(spec.first_name, spec.last_name, 900 + index),
                full_name=f"{spec.first_name} {spec.last_name}",
                password_hash=hash_password(spec.password),
                must_change_password=False,
                is_superuser=False,
                default_property_id=self.hotel_property.id,
                language="tr",
                theme="dark",
                notes=DEMO_MARKER,
            )
            if role is not None:
                user.roles.append(role)
            self.session.add(user)
            self.session.flush()
            self.users[spec.role_code] = user
            self._bump("user")

            self.credentials.append(
                DemoUserCredential(
                    username=spec.username,
                    password=spec.password,
                    role_code=spec.role_code,
                    full_name=user.full_name,
                )
            )

            department = self.departments.get(spec.department_code)
            employee = Employee(
                property_id=self.hotel_property.id,
                department_id=department.id if department else None,
                user_id=user.id,
                employee_code=f"{DEMO_CODE_PREFIX}P{index + 1:02d}",
                first_name=spec.first_name,
                last_name=spec.last_name,
                position=spec.position,
                phone=_demo_phone(900 + index),
                email=user.email,
                employment_status=EmploymentStatus.ACTIVE,
                hire_date=hire_base + timedelta(days=index * 45),
                notes=DEMO_MARKER,
            )
            self.session.add(employee)
            self.employees.append(employee)
            self._bump("employee")

        for offset, (first, last, department_code, position) in enumerate(EXTRA_EMPLOYEES):
            department = self.departments.get(department_code)
            employee = Employee(
                property_id=self.hotel_property.id,
                department_id=department.id if department else None,
                employee_code=f"{DEMO_CODE_PREFIX}P{len(DEMO_USERS) + offset + 1:02d}",
                first_name=first,
                last_name=last,
                position=position,
                phone=_demo_phone(950 + offset),
                email=_demo_email(first, last, 950 + offset),
                employment_status=(
                    EmploymentStatus.ON_LEAVE if offset == 2 else EmploymentStatus.ACTIVE
                ),
                hire_date=hire_base + timedelta(days=300 + offset * 30),
                notes=DEMO_MARKER,
            )
            self.session.add(employee)
            self.employees.append(employee)
            self._bump("employee")
        self.session.flush()

        # Vardiya plani: bugunden itibaren bir hafta.
        shift_cycle = (ShiftType.MORNING, ShiftType.AFTERNOON, ShiftType.NIGHT)
        shift_hours = {
            ShiftType.MORNING: (time(7, 0), time(15, 0)),
            ShiftType.AFTERNOON: (time(15, 0), time(23, 0)),
            ShiftType.NIGHT: (time(23, 0), time(7, 0)),
        }
        for day_offset in range(7):
            shift_date = self.today + timedelta(days=day_offset)
            for position, employee in enumerate(self.employees):
                if employee.employment_status is not EmploymentStatus.ACTIVE:
                    continue
                shift_type = shift_cycle[(position + day_offset) % len(shift_cycle)]
                start_time, end_time = shift_hours[shift_type]
                self.session.add(
                    Shift(
                        employee_id=employee.id,
                        shift_date=shift_date,
                        shift_type=shift_type,
                        start_time=start_time,
                        end_time=end_time,
                    )
                )
                self._bump("shift")
        self.session.flush()

    @property
    def _manager(self) -> User:
        return self.users["manager"]

    @property
    def _frontdesk(self) -> User:
        return self.users["frontdesk"]

    @property
    def _housekeepers(self) -> list[Employee]:
        housekeeping_department = self.departments.get("KAT")
        if housekeeping_department is None:
            return self.employees
        return [
            employee
            for employee in self.employees
            if employee.department_id == housekeeping_department.id
        ] or self.employees

    @property
    def _technician(self) -> Employee:
        technical_department = self.departments.get("TEKNIK")
        for employee in self.employees:
            if technical_department and employee.department_id == technical_department.id:
                return employee
        return self.employees[0]

    # ================================================================
    #  6. Kurumsal musteriler, acenteler, tedarikciler
    # ================================================================
    def create_partners(self) -> None:
        company_specs = (
            ("FIRMA1", "Ornek Yazilim Ticaret A.S.", "12.00", "250000.00", 30),
            ("FIRMA2", "Ornek Insaat Sanayi Ltd. Sti.", "8.00", "150000.00", 45),
        )
        for index, (code, name, discount, limit, terms) in enumerate(company_specs):
            company = Company(
                code=f"{DEMO_CODE_PREFIX}{code}",
                name=name,
                tax_office="Ornek Vergi Dairesi",
                tax_number=f"111111111{index}",
                contact_person=f"{FIRST_NAMES[index]} {SURNAMES[index]}",
                phone=_demo_phone(800 + index),
                email=_demo_email("kurumsal", code.lower(), 800 + index),
                city="Antalya",
                discount_percent=_money(discount),
                credit_limit=_money(limit),
                payment_terms_days=terms,
                currency=Currency.TRY,
                notes=DEMO_MARKER,
            )
            self.session.add(company)
            self.companies.append(company)
            self._bump("company")

        agency_specs = (
            ("ACENTE1", "Ornek Tur Seyahat Acentesi", "12.00"),
            ("ACENTE2", "Mavi Kiyi Tur Operatoru", "15.00"),
        )
        for index, (code, name, commission) in enumerate(agency_specs):
            agency = Agency(
                code=f"{DEMO_CODE_PREFIX}{code}",
                name=name,
                tax_office="Ornek Vergi Dairesi",
                tax_number=f"222222222{index}",
                contact_person=f"{FIRST_NAMES[index + 5]} {SURNAMES[index + 5]}",
                phone=_demo_phone(810 + index),
                email=_demo_email("acente", code.lower(), 810 + index),
                commission_percent=_money(commission),
                contract_start=self.today - timedelta(days=200),
                contract_end=self.today + timedelta(days=165),
                notes=DEMO_MARKER,
            )
            self.session.add(agency)
            self.agencies.append(agency)
            self._bump("agency")

        supplier_specs = (
            ("TED1", "Ornek Gida Toptan Ltd.", 30, 5),
            ("TED2", "Ornek Temizlik Malzemeleri", 15, 4),
            ("TED3", "Ornek Tekstil ve Otelcilik", 45, 3),
        )
        for index, (code, name, terms, rating) in enumerate(supplier_specs):
            supplier = Supplier(
                code=f"{DEMO_CODE_PREFIX}{code}",
                name=name,
                contact_person=f"{FIRST_NAMES[index + 10]} {SURNAMES[index + 10]}",
                phone=_demo_phone(820 + index),
                email=_demo_email("tedarik", code.lower(), 820 + index),
                address_line="Ornek Sanayi Sitesi No: 5",
                tax_office="Ornek Vergi Dairesi",
                tax_number=f"333333333{index}",
                payment_terms_days=terms,
                rating=rating,
                notes=DEMO_MARKER,
            )
            self.session.add(supplier)
            self.suppliers.append(supplier)
            self._bump("supplier")
        self.session.flush()

    # ================================================================
    #  7. Stok
    # ================================================================
    def create_inventory(self) -> None:
        warehouse_specs = (
            ("ANA", "Ana Depo", "Bodrum kat", True),
            ("KAT", "Kat Deposu", "2. kat servis odasi", False),
            ("BAR", "Bar Deposu", "Lobi bar arkasi", False),
        )
        for code, name, location, is_default in warehouse_specs:
            warehouse = Warehouse(
                property_id=self.hotel_property.id,
                code=code,
                name=name,
                location=location,
                is_default=is_default,
                notes=DEMO_MARKER,
            )
            self.session.add(warehouse)
            self.warehouses.append(warehouse)
            self._bump("warehouse")
        self.session.flush()

        catalog = (
            (
                "Minibar",
                True,
                (
                    "Su 0.5 lt",
                    "Maden Suyu",
                    "Kola",
                    "Meyve Suyu",
                    "Cikolata",
                    "Tuzlu Kuruyemis",
                    "Bira",
                    "Enerji Icecegi",
                ),
            ),
            (
                "Temizlik",
                False,
                (
                    "Yuzey Temizleyici",
                    "Cam Temizleyici",
                    "Camasir Suyu",
                    "Cop Poseti",
                    "Bulasik Deterjani",
                    "Dezenfektan",
                    "Zemin Cilasi",
                ),
            ),
            (
                "Tekstil",
                False,
                ("Nevresim Takimi", "Yastik Kilifi", "Banyo Havlusu", "El Havlusu", "Paspas"),
            ),
            ("Kirtasiye", False, ("Anahtar Karti", "Kalem", "Not Defteri", "Fatura Kagidi")),
            (
                "Yiyecek-Icecek",
                False,
                ("Kahve Cekirdegi", "Cay", "Seker Sase", "Sut", "Zeytinyagi", "Un"),
            ),
        )
        flattened: list[tuple[str, bool, str]] = [
            (category, is_minibar, name)
            for category, is_minibar, names in catalog
            for name in names
        ]
        target = min(self.profile.inventory_items, len(flattened))

        for index in range(target):
            category, is_minibar, name = flattened[index]
            unit_cost = _random_money(self.rng, "12.00", "320.00")
            minimum = Decimal(self.rng.randrange(10, 60))
            # Her besinci kalem bilincli olarak asgari seviyenin altinda
            # birakilir; boylece "dusuk stok" uyarilari ekrani dolu gorunur.
            below_minimum = index % 5 == 0
            current = (
                Decimal(self.rng.randrange(0, int(minimum)))
                if below_minimum
                else minimum + Decimal(self.rng.randrange(5, 120))
            )
            item = InventoryItem(
                property_id=self.hotel_property.id,
                sku=f"{DEMO_CODE_PREFIX}S{index + 1:03d}",
                barcode=f"869{index:010d}",
                name=name,
                category=category,
                unit="adet" if category != "Yiyecek-Icecek" else "kg",
                current_stock=current,
                minimum_stock=minimum,
                maximum_stock=minimum * 6,
                reorder_quantity=minimum * 2,
                unit_cost=unit_cost,
                sale_price=_money(unit_cost * Decimal("2.5")) if is_minibar else _money("0.00"),
                currency=Currency.TRY,
                tax_rate_percent=_money("20.00"),
                is_minibar_item=is_minibar,
                preferred_supplier_id=self.suppliers[index % len(self.suppliers)].id,
                notes=DEMO_MARKER,
            )
            self.session.add(item)
            self.inventory_items.append(item)
            self._bump("inventory_item")
        self.session.flush()

        main_warehouse = self.warehouses[0]
        for item in self.inventory_items:
            purchase_quantity = item.current_stock + Decimal(self.rng.randrange(10, 60))
            purchase_date = self.today - timedelta(days=self.rng.randint(10, 60))
            self.session.add(
                StockMovement(
                    inventory_item_id=item.id,
                    warehouse_id=main_warehouse.id,
                    movement_type=StockMovementType.PURCHASE_IN,
                    movement_date=purchase_date,
                    quantity=purchase_quantity,
                    unit_cost=item.unit_cost,
                    total_cost=_money(purchase_quantity * item.unit_cost),
                    stock_after=purchase_quantity,
                    reference=f"IRS-{self.rng.randrange(10000, 99999)}",
                )
            )
            self._bump("stock_movement")

            consumed = purchase_quantity - item.current_stock
            if consumed > 0:
                movement_type = (
                    StockMovementType.MINIBAR_OUT
                    if item.is_minibar_item
                    else StockMovementType.CONSUMPTION_OUT
                )
                self.session.add(
                    StockMovement(
                        inventory_item_id=item.id,
                        warehouse_id=main_warehouse.id,
                        movement_type=movement_type,
                        movement_date=purchase_date + timedelta(days=self.rng.randint(1, 9)),
                        quantity=consumed,
                        unit_cost=item.unit_cost,
                        total_cost=_money(consumed * item.unit_cost),
                        stock_after=item.current_stock,
                        reference="Gunluk tuketim",
                    )
                )
                self._bump("stock_movement")

        # Satin alma talepleri: eksik kalemler icin uc farkli asamada talep.
        low_stock = [item for item in self.inventory_items if item.is_below_minimum][:6]
        statuses = (
            PurchaseRequestStatus.DRAFT,
            PurchaseRequestStatus.SUBMITTED,
            PurchaseRequestStatus.APPROVED,
        )
        for index, status in enumerate(statuses):
            request = PurchaseRequest(
                property_id=self.hotel_property.id,
                request_number=f"{DEMO_CODE_PREFIX}ST{index + 1:04d}",
                supplier_id=self.suppliers[index % len(self.suppliers)].id,
                status=status,
                request_date=self.today - timedelta(days=index * 3),
                expected_date=self.today + timedelta(days=7 - index),
                currency=Currency.TRY,
                requested_by_user_id=self._manager.id,
                approved_by_user_id=(
                    self._manager.id if status is PurchaseRequestStatus.APPROVED else None
                ),
                approved_at=(
                    _at(self.today - timedelta(days=index), 10)
                    if status is PurchaseRequestStatus.APPROVED
                    else None
                ),
                notes=DEMO_MARKER,
            )
            for item in low_stock[index * 2 : index * 2 + 2]:
                quantity = item.reorder_quantity or Decimal("10")
                request.lines.append(
                    PurchaseRequestLine(
                        inventory_item_id=item.id,
                        description=item.name,
                        quantity=quantity,
                        unit_price=item.unit_cost,
                        total_amount=_money(quantity * item.unit_cost),
                    )
                )
                self._bump("purchase_request_line")
            request.recalculate()
            self.session.add(request)
            self._bump("purchase_request")
        self.session.flush()

    # ================================================================
    #  8. Misafirler
    # ================================================================
    def create_guests(self) -> None:
        for index in range(self.profile.guests):
            first_name = self.rng.choice(FIRST_NAMES)
            last_name = self.rng.choice(SURNAMES)
            country, language = self.rng.choice(NATIONALITIES)
            is_domestic = country == "Turkiye"

            guest = Guest(
                title=self.rng.choice(
                    [GuestTitle.MR, GuestTitle.MRS, GuestTitle.MS, GuestTitle.NONE]
                ),
                first_name=first_name,
                last_name=last_name,
                birth_date=date(
                    self.rng.randint(1955, 2005),
                    self.rng.randint(1, 12),
                    self.rng.randint(1, 28),
                ),
                nationality=country,
                preferred_language=language,
                identity_document_type=(
                    IdentityDocumentType.NATIONAL_ID
                    if is_domestic
                    else IdentityDocumentType.PASSPORT
                ),
                identity_issuing_country=country,
                identity_expiry=self.today + timedelta(days=self.rng.randint(200, 2500)),
                email=_demo_email(first_name, last_name, index + 1),
                phone=_demo_phone(index + 1),
                mobile=_demo_phone(index + 1),
                address_line="Ornek Mahallesi, Deneme Sokak No: 7",
                city=self.rng.choice(["Antalya", "Istanbul", "Ankara", "Izmir", "Bursa"]),
                postal_code="07000",
                country=country,
                notes=DEMO_MARKER,
            )
            guest.set_identity(self._unique_identity(domestic=is_domestic))

            # VIP dagilimi: ~%15 misafir bir kademede.
            roll = self.rng.random()
            if roll < 0.04:
                guest.vip_level = VIPLevel.PLATINUM
            elif roll < 0.09:
                guest.vip_level = VIPLevel.GOLD
            elif roll < 0.15:
                guest.vip_level = VIPLevel.SILVER

            if self.companies and index % 11 == 0:
                guest.company_id = self.companies[index % len(self.companies)].id
            elif self.agencies and index % 13 == 0:
                guest.agency_id = self.agencies[index % len(self.agencies)].id

            self.session.add(guest)
            self.guests.append(guest)
            self._bump("guest")
        self.session.flush()

        # Kara liste: tam olarak bir misafir. Amac, uyari akisini gostermek.
        #
        # Adi bilerek **rastgele havuzdan alinmaz**. Kara liste etiketi, uretilen
        # ad-soyad birlesimi gercek bir kisiyle rastlanti eseri ortusurse itibar
        # riski dogurur; ustelik bu ekran tanitim sunumuna goruntu olarak girer.
        # Maskeleme burada ise yaramaz - risk bicimde degil, adin etiketle YAN
        # YANA gorunmesindedir. Bu yuzden kara listedeki kayda hicbir kisiye
        # benzemeyen, acikca kurgusal bir ad verilir.
        blacklisted = self.guests[-1]
        blacklisted.first_name = "ORNEK"
        blacklisted.last_name = "KAYIT-01 (DEMO)"
        blacklisted.email = f"ornek.kayit01@{DEMO_EMAIL_DOMAIN}"
        blacklisted.is_blacklisted = True
        blacklisted.blacklist_reason = (
            "Odada agir hasar birakti ve hasar bedeli tahsil edilemedi (demo kaydi)."
        )
        blacklisted.blacklisted_at = _at(self.today - timedelta(days=45), 9)

        preference_pool = (
            ("oda", "Ust katta, asansorden uzak oda"),
            ("oda", "Sigara icilmeyen oda"),
            ("yatak", "Ek yastik (sert)"),
            ("yatak", "Iki ayri yatak"),
            ("yemek", "Glutensiz kahvalti"),
            ("yemek", "Vejetaryen menu"),
            ("genel", "Gec check-out tercihi"),
        )
        for index, guest in enumerate(self.guests):
            if index % 4 == 0:
                category, value = preference_pool[index % len(preference_pool)]
                self.session.add(
                    GuestPreference(
                        guest_id=guest.id,
                        category=category,
                        value=value,
                        is_critical=category == "yemek",
                    )
                )
                self._bump("guest_preference")

            if index % 8 == 3:
                self.session.add(
                    GuestNote(
                        guest_id=guest.id,
                        author_user_id=self._frontdesk.id,
                        content=(
                            "Sadik misafir; her gelisinde ayni odayi tercih ediyor (demo notu)."
                            if index % 16 == 3
                            else "Gurultuye duyarli; sessiz oda talep ediyor (demo notu)."
                        ),
                        is_alert=index % 16 != 3,
                    )
                )
                self._bump("guest_note")

            self.session.add(
                ConsentRecord(
                    guest_id=guest.id,
                    consent_type=ConsentType.DATA_PROCESSING,
                    is_granted=True,
                    granted_at=_at(self.today - timedelta(days=self.rng.randint(1, 300)), 12),
                    source="check-in formu",
                    recorded_by_user_id=self._frontdesk.id,
                )
            )
            self._bump("consent")

            if index % 3 == 0:
                granted = index % 6 == 0
                self.session.add(
                    ConsentRecord(
                        guest_id=guest.id,
                        consent_type=ConsentType.MARKETING_EMAIL,
                        is_granted=granted,
                        granted_at=(_at(self.today - timedelta(days=60), 12) if granted else None),
                        revoked_at=(None if granted else _at(self.today - timedelta(days=20), 12)),
                        source="web sitesi",
                    )
                )
                self._bump("consent")
        self.session.flush()

    def _unique_identity(self, *, domestic: bool) -> str:
        """Daha once kullanilmamis, gecersiz bir kimlik/pasaport numarasi."""
        while True:
            candidate = (
                _fake_identity_number(self.rng) if domestic else _fake_passport_number(self.rng)
            )
            if candidate not in self._used_identities:
                self._used_identities.add(candidate)
                return candidate

    # ================================================================
    #  9. Rezervasyonlar
    # ================================================================
    #: Rezervasyon durum dagilimi. Toplam 1.0'dir; adetler
    #: :func:`_split_count` ile toplam korunarak dagitilir.
    _RESERVATION_MIX: Final[tuple[tuple[str, float], ...]] = (
        ("past", 0.250),
        ("future_confirmed", 0.225),
        ("in_house", 0.150),
        ("future_tentative", 0.0875),
        ("arrival_today", 0.075),
        ("departed_today", 0.075),
        ("departure_today", 0.0625),
        ("cancelled", 0.050),
        ("no_show", 0.025),
    )

    def create_reservations(self) -> None:
        distribution = _split_count(self.profile.reservations, self._RESERVATION_MIX)
        # Sira onemlidir: bugune yakin, en kisitli kovalar once yerlestirilir.
        # Gec kalan kovalar bos araligi daha kolay bulur.
        order = (
            "in_house",
            "arrival_today",
            "departure_today",
            "departed_today",
            "no_show",
            "past",
            "future_confirmed",
            "future_tentative",
            "cancelled",
        )
        for bucket in order:
            for _ in range(distribution.get(bucket, 0)):
                self._create_single_reservation(bucket)
        self.session.flush()

        self._create_stays_and_folios()
        self._update_guest_statistics()
        self._create_waitlist()

    def _bucket_date_range(self, bucket: str) -> DateRange:
        """Kova adina gore tarih araligi uretir (hepsi bugune goredir)."""
        if bucket == "in_house":
            nights = self.rng.randint(2, 7)
            offset = self.rng.randint(1, nights - 1)
            start = self.today - timedelta(days=offset)
            return DateRange(start, start + timedelta(days=nights))
        if bucket == "arrival_today":
            return DateRange(self.today, self.today + timedelta(days=self.rng.randint(1, 6)))
        if bucket in {"departure_today", "departed_today"}:
            return DateRange(self.today - timedelta(days=self.rng.randint(1, 5)), self.today)
        if bucket == "past":
            end = self.today - timedelta(days=self.rng.randint(1, 60))
            return DateRange(end - timedelta(days=self.rng.randint(1, 7)), end)
        if bucket == "future_confirmed":
            start = self.today + timedelta(days=self.rng.randint(1, 80))
            return DateRange(start, start + timedelta(days=self.rng.randint(1, 7)))
        if bucket == "future_tentative":
            start = self.today + timedelta(days=self.rng.randint(5, 85))
            return DateRange(start, start + timedelta(days=self.rng.randint(1, 5)))
        if bucket == "no_show":
            start = self.today - timedelta(days=self.rng.randint(1, 20))
            return DateRange(start, start + timedelta(days=self.rng.randint(1, 3)))
        # cancelled
        start = self.today + timedelta(days=self.rng.randint(-30, 60))
        return DateRange(start, start + timedelta(days=self.rng.randint(1, 4)))

    _BUCKET_STATUS: Final[dict[str, ReservationStatus]] = {
        "in_house": ReservationStatus.CHECKED_IN,
        "arrival_today": ReservationStatus.CONFIRMED,
        # Ayni gun iki ayri sahne: "departure_today" henuz cikis yapmamis
        # (odada, hesabi aciktir), "departed_today" sabah cikmistir (oda bos ve
        # kirlidir, kat hizmetleri kuyrugundadir). Ikisini ayirmadan kat
        # hizmetleri ekrani bos kalirdi; bkz. _sync_room_statuses.
        "departure_today": ReservationStatus.CHECKED_IN,
        "departed_today": ReservationStatus.CHECKED_OUT,
        "past": ReservationStatus.CHECKED_OUT,
        "future_confirmed": ReservationStatus.CONFIRMED,
        "future_tentative": ReservationStatus.TENTATIVE,
        "cancelled": ReservationStatus.CANCELLED,
        "no_show": ReservationStatus.NO_SHOW,
    }

    def _find_free_room(self, requested: DateRange) -> Room | None:
        """Istenen aralikta bos bir oda bulur; yoksa ``None``.

        Odalar karistirilarak taranir ki doluluk belirli odalara yigilmasin.
        Cakisma karari :mod:`app.domain.rules.availability` tarafindan verilir;
        boylece demo veri, uygulamanin kendi kuraliyla tutarli olur.
        """
        candidates = list(self.rooms)
        self.rng.shuffle(candidates)
        for room in candidates:
            if is_room_available(
                requested,
                room_id=room.id,
                existing_bookings=self._bookings,
                blocks=self._blocks,
            ):
                return room
        return None

    def _create_single_reservation(self, bucket: str) -> None:
        requested: DateRange | None = None
        room: Room | None = None
        # Birkac deneme: tarih araligi doluysa yeni bir aralik denenir.
        for _ in range(12):
            candidate_range = self._bucket_date_range(bucket)
            candidate_room = self._find_free_room(candidate_range)
            if candidate_room is not None:
                requested, room = candidate_range, candidate_room
                break
        if requested is None or room is None:
            log.debug("demo_rezervasyon_yerlestirilemedi", bucket=bucket)
            return

        status = self._BUCKET_STATUS[bucket]
        guest = self.rng.choice(self.guests)
        room_type = next(rt for rt in self.room_types.values() if rt.id == room.room_type_id)
        rate_plan = self.rng.choice(self.rate_plans)

        adults = self.rng.randint(1, min(2, room_type.max_adults))
        children = self.rng.randint(0, 1) if room_type.max_children else 0
        discount = _money("0.00")
        company_id: int | None = None
        agency_id: int | None = None
        source = self.rng.choice(
            [
                ReservationSource.DIRECT,
                ReservationSource.PHONE,
                ReservationSource.WEBSITE,
                ReservationSource.BOOKING_COM,
                ReservationSource.WALK_IN,
                ReservationSource.EMAIL,
            ]
        )
        if guest.company_id is not None:
            company_id = guest.company_id
            source = ReservationSource.CORPORATE
            discount = _money("10.00")
        elif guest.agency_id is not None:
            agency_id = guest.agency_id
            source = ReservationSource.AGENCY
            discount = _money("5.00")

        breakdown = calculate_stay_price(
            requested,
            rules=self.rate_rules.get((rate_plan.id, room_type.id), []),
            base_rate=room_type.base_rate,
            currency=Currency.TRY,
            adults=adults,
            children=children,
            base_occupancy=room_type.base_occupancy,
            extra_adult_rate=room_type.extra_adult_rate,
            extra_child_rate=room_type.extra_child_rate,
            discount_percent=discount,
            tax_rate_percent=_money("10.00"),
            tax_included_in_rate=True,
        )

        sequence = self._next_sequence()
        reservation = Reservation(
            property_id=self.hotel_property.id,
            confirmation_number=f"DM{sequence:06d}",
            status=status,
            source=source,
            source_reference=(
                f"BK-{sequence:07d}" if source is ReservationSource.BOOKING_COM else None
            ),
            primary_guest_id=guest.id,
            company_id=company_id,
            agency_id=agency_id,
            check_in_date=requested.start,
            check_out_date=requested.end,
            expected_arrival_time=time(self.rng.randint(13, 21), 0),
            adults=adults,
            children=children,
            currency=Currency.TRY,
            deposit_amount=_money(breakdown.total.amount * Decimal("0.30")),
            created_by_user_id=self._frontdesk.id,
            special_requests=(
                "Ust kat tercih ediliyor (demo talebi)." if sequence % 7 == 0 else None
            ),
            notes=DEMO_MARKER,
        )
        if status is ReservationStatus.CANCELLED:
            reservation.cancelled_at = _at(self.today - timedelta(days=self.rng.randint(1, 20)), 11)
            reservation.cancellation_reason = "Misafir seyahat planini degistirdi (demo)."
            reservation.cancelled_by_user_id = self._frontdesk.id
        elif status is ReservationStatus.NO_SHOW:
            reservation.no_show_marked_at = _at(requested.start + timedelta(days=1), 6)

        reservation_room = ReservationRoom(
            room_type_id=room_type.id,
            room_id=room.id,
            rate_plan_id=rate_plan.id,
            check_in_date=requested.start,
            check_out_date=requested.end,
            adults=adults,
            children=children,
            meal_plan=rate_plan.meal_plan,
            nightly_rate=_money(breakdown.average_nightly_rate.amount),
            total_amount=_money(breakdown.total.amount),
            discount_percent=discount,
        )
        reservation_room.reservation_guests.append(
            ReservationGuest(
                guest_id=guest.id,
                relation=GuestRelation.PRIMARY,
                is_primary=True,
            )
        )
        reservation.rooms.append(reservation_room)
        reservation.recalculate_summary()

        self.session.add(reservation)
        self.reservations.append(reservation)
        self._bump("reservation")
        self._bump("reservation_room")
        self._bump("reservation_guest")

        self._bookings.append(
            Booking(
                room_id=room.id,
                date_range=requested,
                reservation_id=None,
                confirmation_number=reservation.confirmation_number,
            )
        )

    # ---------------- konaklama, folyo, ucret, odeme ----------------
    def _create_stays_and_folios(self) -> None:
        minibar_items = [item for item in self.inventory_items if item.is_minibar_item]

        for reservation in self.reservations:
            if reservation.status not in {
                ReservationStatus.CHECKED_IN,
                ReservationStatus.CHECKED_OUT,
                ReservationStatus.CONFIRMED,
            }:
                continue
            reservation_room = reservation.rooms[0]
            if reservation_room.room_id is None:
                continue

            is_departed = reservation.status is ReservationStatus.CHECKED_OUT
            is_in_house = reservation.status is ReservationStatus.CHECKED_IN
            has_stay = is_departed or is_in_house

            stay: Stay | None = None
            if has_stay:
                stay = Stay(
                    reservation_room_id=reservation_room.id,
                    room_id=reservation_room.room_id,
                    status=StayStatus.DEPARTED if is_departed else StayStatus.IN_HOUSE,
                    actual_check_in=_at(reservation_room.check_in_date, 15, 30),
                    actual_check_out=(
                        _at(reservation_room.check_out_date, 11, 15) if is_departed else None
                    ),
                    key_card_count=self.rng.randint(1, 2),
                    key_cards_returned=1 if is_departed else 0,
                    checked_in_by_user_id=self._frontdesk.id,
                    checked_out_by_user_id=self._frontdesk.id if is_departed else None,
                )
                self.session.add(stay)
                self.stays.append(stay)
                self._bump("stay")
            elif self.rng.random() < 0.5:
                # Gelecek rezervasyonlarin yaklasik yarisi kaporasizdir;
                # onlar icin folyo girise kadar acilmaz.
                continue

            folio = Folio(
                property_id=self.hotel_property.id,
                folio_number=f"DF{self._next_sequence():06d}",
                reservation_id=reservation.id,
                reservation_room_id=reservation_room.id,
                guest_id=reservation.primary_guest_id,
                company_id=reservation.company_id,
                status=FolioStatus.CLOSED if is_departed else FolioStatus.OPEN,
                currency=Currency.TRY,
                opened_at=(
                    _at(reservation_room.check_in_date, 15, 30)
                    if has_stay
                    else _at(self.today, 10, 0)
                ),
                closed_at=(_at(reservation_room.check_out_date, 11, 20) if is_departed else None),
                closed_by_user_id=self._frontdesk.id if is_departed else None,
                notes=DEMO_MARKER,
            )

            # Girise kadar oda ucreti islenmez; folyoda yalnizca kapora durur.
            # Bu, bakiyeyi negatif (misafir lehine) gosterir ve gerceke uygundur.
            if has_stay:
                self._add_room_charges(folio, reservation_room)
                self._add_extra_charges(folio, reservation_room)
            folio.recalculate()

            self._add_payments(folio, reservation, is_departed=is_departed, has_stay=has_stay)
            folio.recalculate()

            reservation.paid_amount = folio.total_payments
            reservation.deposit_paid = folio.total_payments > 0

            self.session.add(folio)
            self.folios.append(folio)
            self._bump("folio")

            if is_in_house and minibar_items and stay is not None and self.rng.random() < 0.45:
                self._add_minibar_consumption(folio, reservation_room, stay, minibar_items)

        self.session.flush()
        self._create_invoices()
        self._create_cash_entries()

    def _add_room_charges(self, folio: Folio, reservation_room: ReservationRoom) -> None:
        """Her gece icin bir oda ucreti satiri isler.

        Fiyat vergi **dahil** ilan edildigi icin, brut tutar net + vergi olarak
        ayristirilir. Aksi halde ``compute_totals`` verginin uzerine bir kez
        daha vergi eklerdi ve folyo toplami rezervasyon tutarini asardi.
        """
        gross_nightly = reservation_room.nightly_rate
        net_nightly = _money(gross_nightly / Decimal("1.10"))
        for day in reservation_room.date_range:
            charge = Charge(
                charge_type=ChargeType.ROOM,
                description=f"Oda ucreti - {day.strftime('%d.%m.%Y')}",
                charge_date=day,
                quantity=Decimal("1.000"),
                unit_price=net_nightly,
                tax_rate_percent=_money("10.00"),
                posted_by_user_id=self._frontdesk.id,
            )
            charge.compute_totals()
            folio.charges.append(charge)
            self._bump("charge")

    def _add_extra_charges(self, folio: Folio, reservation_room: ReservationRoom) -> None:
        extras = (
            (ChargeType.SPA, "SPA masaji", "SPA_MASAJ", Decimal("1.000")),
            (ChargeType.LAUNDRY, "Camasir hizmeti", "CAMASIR", Decimal("2.000")),
            (ChargeType.PARKING, "Otopark", "OTOPARK", Decimal("1.000")),
            (ChargeType.RESTAURANT, "Restoran adisyonu", None, Decimal("1.000")),
            (ChargeType.TRANSFER, "Havalimani transferi", "TRANSFER", Decimal("1.000")),
        )
        for _ in range(self.rng.randint(0, 2)):
            charge_type, description, service_code, quantity = self.rng.choice(extras)
            service = self.services.get(service_code) if service_code else None
            unit_price = (
                service.unit_price
                if service is not None
                else _random_money(self.rng, "250.00", "1800.00")
            )
            charge = Charge(
                charge_type=charge_type,
                service_id=service.id if service is not None else None,
                description=description,
                charge_date=reservation_room.check_in_date
                + timedelta(days=self.rng.randint(0, max(reservation_room.nights - 1, 0))),
                quantity=quantity,
                unit_price=_money(unit_price),
                tax_rate_percent=_money("20.00"),
                reference=f"ADS-{self.rng.randrange(1000, 9999)}",
                posted_by_user_id=self._frontdesk.id,
            )
            charge.compute_totals()
            folio.charges.append(charge)
            self._bump("charge")

    def _add_payments(
        self,
        folio: Folio,
        reservation: Reservation,
        *,
        is_departed: bool,
        has_stay: bool,
    ) -> None:
        if not has_stay:
            # Kapora: rezervasyon tutarinin %30'u, dun tahsil edilmis.
            deposit = reservation.deposit_amount
            if deposit <= 0:
                return
            folio.payments.append(
                Payment(
                    method=PaymentMethod.ONLINE,
                    status=PaymentStatus.PAID,
                    amount=deposit,
                    currency=Currency.TRY,
                    paid_at=_at(self.today - timedelta(days=1), 14, 0),
                    reference=f"KPR-{self._next_sequence():06d}",
                    is_deposit=True,
                    received_by_user_id=self._frontdesk.id,
                )
            )
            self._bump("payment")
            return

        total = folio.total_charges
        if total <= 0:
            return

        if is_departed:
            # Cikis yapmis misafirin hesabi kapanmistir: bakiye tam sifir.
            method = self.rng.choice(
                [PaymentMethod.CREDIT_CARD, PaymentMethod.CASH, PaymentMethod.BANK_TRANSFER]
            )
            folio.payments.append(
                Payment(
                    method=method,
                    status=PaymentStatus.PAID,
                    amount=total,
                    currency=Currency.TRY,
                    paid_at=_at(reservation.check_out_date, 11, 10),
                    reference=f"ODM-{self._next_sequence():06d}",
                    card_last_four=(
                        f"{self.rng.randrange(0, 10000):04d}"
                        if method is PaymentMethod.CREDIT_CARD
                        else None
                    ),
                    received_by_user_id=self._frontdesk.id,
                )
            )
            self._bump("payment")
            return

        # Otelde: hesabin bir kismi giriste tahsil edilmis, kalani cikista.
        advance = _money(total * Decimal("0.40"))
        if advance <= 0:
            return
        folio.payments.append(
            Payment(
                method=PaymentMethod.CREDIT_CARD,
                status=PaymentStatus.PAID,
                amount=advance,
                currency=Currency.TRY,
                paid_at=_at(reservation.check_in_date, 15, 45),
                reference=f"KPR-{self._next_sequence():06d}",
                card_last_four=f"{self.rng.randrange(0, 10000):04d}",
                is_deposit=True,
                received_by_user_id=self._frontdesk.id,
            )
        )
        self._bump("payment")

    def _add_minibar_consumption(
        self,
        folio: Folio,
        reservation_room: ReservationRoom,
        stay: Stay,
        minibar_items: list[InventoryItem],
    ) -> None:
        item = self.rng.choice(minibar_items)
        quantity = Decimal(self.rng.randint(1, 3))
        total = _money(quantity * item.sale_price)
        charge = Charge(
            charge_type=ChargeType.MINIBAR,
            description=f"Minibar - {item.name}",
            charge_date=self.today,
            quantity=quantity,
            unit_price=item.sale_price,
            tax_rate_percent=item.tax_rate_percent,
            reference="Minibar fisi",
            posted_by_user_id=self._frontdesk.id,
        )
        charge.compute_totals()
        folio.charges.append(charge)
        self._bump("charge")
        folio.recalculate()
        self.session.flush()

        self.session.add(
            MinibarConsumption(
                room_id=reservation_room.room_id,
                inventory_item_id=item.id,
                stay_id=stay.id,
                folio_id=folio.id,
                charge_id=charge.id,
                consumption_date=self.today,
                quantity=quantity,
                unit_price=item.sale_price,
                total_amount=total,
                recorded_by_employee_id=self._housekeepers[0].id,
                is_charged=True,
            )
        )
        self._bump("minibar_consumption")

    def _create_invoices(self) -> None:
        """Kapanmis kurumsal folyolar icin fatura uretir."""
        closed_company_folios = [
            folio
            for folio in self.folios
            if folio.status is FolioStatus.CLOSED and folio.company_id is not None
        ][:5]
        for index, folio in enumerate(closed_company_folios):
            company = next((c for c in self.companies if c.id == folio.company_id), None)
            invoice = Invoice(
                folio_id=folio.id,
                property_id=self.hotel_property.id,
                invoice_number=f"DFT{self.today.year}{index + 1:05d}",
                status=InvoiceStatus.ISSUED,
                issue_date=self.today - timedelta(days=index + 1),
                due_date=self.today + timedelta(days=30),
                customer_name=company.name if company else "Demo Kurumsal Musteri",
                customer_tax_office=company.tax_office if company else None,
                customer_tax_number=company.tax_number if company else None,
                customer_address=company.address_line if company else None,
                customer_email=company.email if company else None,
                currency=Currency.TRY,
                notes=DEMO_MARKER,
            )
            for order, charge in enumerate(folio.charges):
                invoice.lines.append(
                    InvoiceLine(
                        description=charge.description,
                        quantity=charge.quantity,
                        unit_price=charge.unit_price,
                        net_amount=charge.net_amount,
                        tax_rate_percent=charge.tax_rate_percent,
                        tax_amount=charge.tax_amount,
                        total_amount=charge.total_amount,
                        sort_order=order,
                    )
                )
                self._bump("invoice_line")
            invoice.recalculate()
            self.session.add(invoice)
            self._bump("invoice")

    def _create_cash_entries(self) -> None:
        """Son bir haftanin tahsilatlarini ve birkac gideri kasaya isler."""
        recent = self.today - timedelta(days=7)
        for folio in self.folios:
            for payment in folio.payments:
                entry_date = payment.paid_at.date()
                if entry_date < recent or entry_date > self.today:
                    continue
                self.session.add(
                    CashRegisterEntry(
                        property_id=self.hotel_property.id,
                        entry_date=entry_date,
                        direction=TransactionDirection.INCOME,
                        method=payment.method,
                        category="Oda Geliri",
                        description=f"{folio.folio_number} tahsilati",
                        amount=payment.amount,
                        currency=Currency.TRY,
                        folio_id=folio.id,
                        recorded_by_user_id=self.users["accounting"].id,
                    )
                )
                self._bump("cash_entry")

        expenses = (
            ("Temizlik Malzemesi", "Aylik temizlik malzemesi alimi", "18500.00"),
            ("Personel Avansi", "Kat hizmetleri personel avansi", "5000.00"),
            ("Bakim Onarim", "Asansor periyodik bakim bedeli", "12750.00"),
            ("Enerji", "Elektrik faturasi", "42300.00"),
        )
        for index, (category, description, amount) in enumerate(expenses):
            self.session.add(
                CashRegisterEntry(
                    property_id=self.hotel_property.id,
                    entry_date=self.today - timedelta(days=index + 1),
                    direction=TransactionDirection.EXPENSE,
                    method=PaymentMethod.BANK_TRANSFER,
                    category=category,
                    description=description,
                    amount=_money(amount),
                    currency=Currency.TRY,
                    recorded_by_user_id=self.users["accounting"].id,
                )
            )
            self._bump("cash_entry")

        self.session.add(
            CashRegisterEntry(
                property_id=self.hotel_property.id,
                entry_date=self.today - timedelta(days=1),
                direction=TransactionDirection.INCOME,
                method=PaymentMethod.CASH,
                category="Gun Sonu",
                description="Gun sonu kasa kapanisi (demo)",
                amount=_money("0.00"),
                currency=Currency.TRY,
                recorded_by_user_id=self.users["accounting"].id,
                is_day_close=True,
            )
        )
        self._bump("cash_entry")

    def _update_guest_statistics(self) -> None:
        """Misafir CRM ozetlerini gerceklesmis konaklamalardan doldurur.

        Bu alanlar denormalize ozetlerdir (bkz. ``Guest`` modeli): rapor
        performansi icin tutulurlar. Demo veride bos birakilsalardi CRM ekrani
        her misafiri "hic konaklamamis" gosterirdi.
        """
        by_guest: dict[int, Guest] = {guest.id: guest for guest in self.guests}
        stay_days: dict[int, list[date]] = {}

        for reservation in self.reservations:
            guest = by_guest.get(reservation.primary_guest_id)
            if guest is None:
                continue
            if reservation.status is ReservationStatus.CHECKED_OUT:
                guest.total_stays += 1
                guest.total_nights += reservation.nights
                guest.total_revenue = _money(guest.total_revenue + reservation.total_amount)
                stay_days.setdefault(guest.id, []).append(reservation.check_in_date)
            elif reservation.status is ReservationStatus.CANCELLED:
                guest.cancellation_count += 1
            elif reservation.status is ReservationStatus.NO_SHOW:
                guest.no_show_count += 1

        for guest_id, days in stay_days.items():
            guest = by_guest[guest_id]
            guest.first_stay_date = min(days)
            guest.last_stay_date = max(days)

    def _create_waitlist(self) -> None:
        for index in range(4):
            guest = self.guests[index % len(self.guests)]
            start = self.today + timedelta(days=40 + index * 5)
            self.session.add(
                WaitlistEntry(
                    property_id=self.hotel_property.id,
                    guest_id=guest.id,
                    room_type_id=self.room_types["SUIT"].id if index % 2 else None,
                    contact_name=guest.full_name,
                    contact_phone=guest.phone,
                    contact_email=guest.email,
                    requested_check_in=start,
                    requested_check_out=start + timedelta(days=3),
                    adults=2,
                    children=index % 2,
                    priority=index,
                    notes=DEMO_MARKER,
                )
            )
            self._bump("waitlist")

    # ================================================================
    #  10. Operasyon: kat hizmetleri, teknik servis, kayip esya
    # ================================================================
    def create_operations(self) -> None:
        self._sync_room_statuses()
        self._create_housekeeping_tasks()
        self._create_maintenance_tickets()
        self._create_lost_and_found()
        self.session.flush()

    def _sync_room_statuses(self) -> None:
        """Oda durumlarini fiili konaklamalarla tutarli hale getirir.

        Bunu rezervasyonlardan **sonra** yapmak gerekir: hangi odanin dolu
        oldugu ancak yerlestirme bittikten sonra bellidir. Bloke odalarin
        durumu korunur, aksi halde "arizali ama temiz" gibi celiskili bir
        durum yazilirdi.
        """
        occupied_room_ids = {stay.room_id for stay in self.stays if stay.actual_check_out is None}
        departed_today_room_ids = {
            stay.room_id
            for stay in self.stays
            if stay.actual_check_out is not None and stay.actual_check_out.date() == self.today
        }

        for index, room in enumerate(self.rooms):
            if room.housekeeping_status in {
                RoomHousekeepingStatus.OUT_OF_ORDER,
                RoomHousekeepingStatus.OUT_OF_SERVICE,
            }:
                continue
            if room.id in occupied_room_ids:
                room.occupancy_status = RoomOccupancyStatus.OCCUPIED
                room.housekeeping_status = (
                    RoomHousekeepingStatus.DIRTY if index % 3 == 0 else RoomHousekeepingStatus.CLEAN
                )
            elif room.id in departed_today_room_ids:
                room.occupancy_status = RoomOccupancyStatus.VACANT
                room.housekeeping_status = RoomHousekeepingStatus.DIRTY
            else:
                room.occupancy_status = RoomOccupancyStatus.VACANT
                room.housekeeping_status = (
                    RoomHousekeepingStatus.INSPECTED
                    if index % 4 == 1
                    else RoomHousekeepingStatus.CLEAN
                )

    def _create_housekeeping_tasks(self) -> None:
        housekeepers = self._housekeepers
        statuses = (
            HousekeepingStatus.PENDING,
            HousekeepingStatus.ASSIGNED,
            HousekeepingStatus.IN_PROGRESS,
            HousekeepingStatus.COMPLETED,
            HousekeepingStatus.INSPECTED,
        )
        # Satisa kapali odalara temizlik gorevi acilmaz; teknik servis
        # bitirmeden kat hizmetleri o odaya girmez.
        rooms = [
            room
            for room in self.rooms
            if room.housekeeping_status
            not in {RoomHousekeepingStatus.OUT_OF_ORDER, RoomHousekeepingStatus.OUT_OF_SERVICE}
        ]
        target = min(self.profile.housekeeping_tasks, len(rooms))
        self.rng.shuffle(rooms)

        for index in range(target):
            room = rooms[index]
            status = statuses[index % len(statuses)]
            if room.occupancy_status is RoomOccupancyStatus.OCCUPIED:
                task_type = HousekeepingTaskType.DAILY_CLEANING
            elif room.housekeeping_status is RoomHousekeepingStatus.DIRTY:
                task_type = HousekeepingTaskType.CHECKOUT_CLEANING
            else:
                task_type = self.rng.choice(
                    [
                        HousekeepingTaskType.INSPECTION,
                        HousekeepingTaskType.LINEN_CHANGE,
                        HousekeepingTaskType.MINIBAR_REFILL,
                    ]
                )

            employee = housekeepers[index % len(housekeepers)]
            started = status in {
                HousekeepingStatus.IN_PROGRESS,
                HousekeepingStatus.COMPLETED,
                HousekeepingStatus.INSPECTED,
            }
            completed = status in {HousekeepingStatus.COMPLETED, HousekeepingStatus.INSPECTED}

            self.session.add(
                HousekeepingTask(
                    property_id=self.hotel_property.id,
                    room_id=room.id,
                    task_type=task_type,
                    status=status,
                    priority=(
                        Priority.HIGH
                        if task_type is HousekeepingTaskType.CHECKOUT_CLEANING
                        else Priority.NORMAL
                    ),
                    scheduled_date=self.today,
                    assigned_employee_id=(
                        None if status is HousekeepingStatus.PENDING else employee.id
                    ),
                    started_at=_at(self.today, 9 + index % 6) if started else None,
                    completed_at=_at(self.today, 10 + index % 6) if completed else None,
                    inspected_at=(
                        _at(self.today, 11 + index % 5)
                        if status is HousekeepingStatus.INSPECTED
                        else None
                    ),
                    inspected_by_employee_id=(
                        housekeepers[0].id if status is HousekeepingStatus.INSPECTED else None
                    ),
                    estimated_minutes=30 if task_type != HousekeepingTaskType.DEEP_CLEANING else 90,
                    actual_minutes=self.rng.randint(20, 55) if completed else None,
                    inspection_passed=(True if status is HousekeepingStatus.INSPECTED else None),
                )
            )
            self._bump("housekeeping_task")

    def _create_maintenance_tickets(self) -> None:
        issues = (
            (MaintenanceCategory.PLUMBING, "Banyo giderinde tikanma", "Su yavas cekiliyor."),
            (MaintenanceCategory.ELECTRICAL, "Priz calismiyor", "Yatak basi priz olu."),
            (MaintenanceCategory.HVAC, "Klima sogutmuyor", "Klima motoru ariza veriyor."),
            (MaintenanceCategory.FURNITURE, "Sandalye kirik", "Calisma masasi sandalyesi kirik."),
            (
                MaintenanceCategory.ELECTRONICS,
                "Televizyon acilmiyor",
                "Guc dugmesi yanit vermiyor.",
            ),
            (MaintenanceCategory.ELEVATOR, "Asansor sesli calisiyor", "2 numarali asansor."),
            (MaintenanceCategory.IT_NETWORK, "Wi-Fi kopmasi", "3. katta sinyal zayif."),
            (MaintenanceCategory.SAFETY, "Yangin tupu suresi doldu", "Koridor tupu degismeli."),
            (MaintenanceCategory.STRUCTURAL, "Duvar boyasi kabarmis", "Nem kaynakli kabarma."),
            (MaintenanceCategory.OTHER, "Kapi kilidi zor aciliyor", "Kart okuyucu gecikmeli."),
        )
        open_statuses = (
            MaintenanceStatus.OPEN,
            MaintenanceStatus.ASSIGNED,
            MaintenanceStatus.IN_PROGRESS,
            MaintenanceStatus.WAITING_PARTS,
        )
        closed_statuses = (MaintenanceStatus.RESOLVED, MaintenanceStatus.CLOSED)
        technician = self._technician
        blocked_room = self.rooms[-1] if self.rooms else None
        target = min(self.profile.maintenance_tickets, len(issues))

        for index in range(target):
            category, title, description = issues[index]
            is_open = index % 2 == 0
            status = (
                open_statuses[index % len(open_statuses)]
                if is_open
                else closed_statuses[index % len(closed_statuses)]
            )
            reported_at = _at(self.today - timedelta(days=self.rng.randint(0, 14)), 8 + index % 8)
            # Uc numarali ariza (klima) odayi bloke eder; oda zaten
            # OUT_OF_ORDER isaretlenmisti - kayit ve oda durumu boylece tutarli.
            blocks_room = index == 2 and blocked_room is not None

            ticket = MaintenanceTicket(
                property_id=self.hotel_property.id,
                ticket_number=f"DA{index + 1:05d}",
                room_id=(
                    blocked_room.id
                    if blocks_room
                    else (self.rooms[index % len(self.rooms)].id if index % 3 else None)
                ),
                location_description=None if index % 3 else "Lobi - ana koridor",
                category=category,
                status=status,
                priority=(
                    Priority.URGENT
                    if blocks_room
                    else self.rng.choice([Priority.LOW, Priority.NORMAL, Priority.HIGH])
                ),
                title=title,
                description=f"{description} (demo kaydi)",
                reported_at=reported_at,
                reported_by_user_id=self._frontdesk.id,
                assigned_employee_id=(
                    technician.id if status is not MaintenanceStatus.OPEN else None
                ),
                assigned_at=(
                    reported_at + timedelta(hours=2)
                    if status is not MaintenanceStatus.OPEN
                    else None
                ),
                resolved_at=(reported_at + timedelta(hours=26) if not is_open else None),
                closed_at=(
                    reported_at + timedelta(hours=30)
                    if status is MaintenanceStatus.CLOSED
                    else None
                ),
                blocks_room=blocks_room,
                block_from=self.today if blocks_room else None,
                block_until=self.today + timedelta(days=3) if blocks_room else None,
                is_preventive=index == 5,
                recurrence_days=180 if index == 5 else None,
                next_due_date=self.today + timedelta(days=180) if index == 5 else None,
                labor_cost=_random_money(self.rng, "0.00", "2500.00"),
                parts_cost=_money("0.00"),
                resolution_notes=("Parca degistirildi, test edildi." if not is_open else None),
                notes=DEMO_MARKER,
            )

            if index % 4 == 1:
                item = self.inventory_items[index % len(self.inventory_items)]
                quantity = Decimal("2.000")
                ticket.parts.append(
                    MaintenancePart(
                        inventory_item_id=item.id,
                        description=item.name,
                        quantity=quantity,
                        unit_cost=item.unit_cost,
                        total_cost=_money(quantity * item.unit_cost),
                    )
                )
                ticket.parts_cost = _money(quantity * item.unit_cost)
                self._bump("maintenance_part")

            self.session.add(ticket)
            self._bump("maintenance_ticket")

    def _create_lost_and_found(self) -> None:
        items = (
            ("Siyah gunes gozlugu", "205 numarali oda", LostItemStatus.STORED),
            ("Sarj kablosu", "Lobi oturma grubu", LostItemStatus.FOUND),
            ("Cocuk oyuncagi", "Havuz basi", LostItemStatus.CLAIMED),
            ("Kol saati", "Restoran", LostItemStatus.RETURNED),
            ("Sapka", "Otopark", LostItemStatus.FOUND),
            ("Kitap", "Toplanti salonu", LostItemStatus.DISPOSED),
        )
        for index, (description, location, status) in enumerate(items):
            self.session.add(
                LostAndFoundItem(
                    property_id=self.hotel_property.id,
                    room_id=self.rooms[index % len(self.rooms)].id if index % 2 == 0 else None,
                    guest_id=(
                        self.guests[index % len(self.guests)].id
                        if status in {LostItemStatus.CLAIMED, LostItemStatus.RETURNED}
                        else None
                    ),
                    item_description=description,
                    found_location=location,
                    found_date=self.today - timedelta(days=index * 2),
                    found_by_employee_id=self._housekeepers[index % len(self._housekeepers)].id,
                    status=status,
                    storage_location="Kayip esya dolabi - raf 2",
                    returned_at=(
                        _at(self.today - timedelta(days=index), 16)
                        if status is LostItemStatus.RETURNED
                        else None
                    ),
                    returned_to=(
                        "Misafirin kendisi" if status is LostItemStatus.RETURNED else None
                    ),
                    notes=DEMO_MARKER,
                )
            )
            self._bump("lost_and_found")

    # ================================================================
    #  11. Sistem kayitlari
    # ================================================================
    def create_system_records(self) -> None:
        self._create_settings()
        self._create_notifications()
        self._create_audit_logs()
        self.session.flush()

    def _create_settings(self) -> None:
        settings = (
            ("varsayilan_kdv_orani", "10", "float", "vergi", "Varsayilan konaklama KDV orani (%)"),
            ("erken_giris_ucret_yuzdesi", "25", "float", "on_buro", "Erken giris ucreti (%)"),
            ("gec_cikis_ucret_yuzdesi", "25", "float", "on_buro", "Gec cikis ucreti (%)"),
            ("kahvalti_fiyata_dahil", "true", "bool", "genel", "Kahvalti fiyata dahil mi?"),
            ("gun_sonu_saati", "23:59", "str", "finans", "Gun sonu kapanis saati"),
            ("dusuk_stok_uyarisi", "true", "bool", "stok", "Dusuk stok bildirimi uret"),
        )
        for key, value, value_type, category, label in settings:
            self.session.add(
                Setting(
                    property_id=self.hotel_property.id,
                    key=key,
                    value=value,
                    value_type=value_type,
                    category=category,
                    label=label,
                    description="Demo kurulumunda uretilen ornek ayar.",
                )
            )
            self._bump("setting")

    def _create_notifications(self) -> None:
        arrivals = sum(
            1
            for reservation in self.reservations
            if reservation.check_in_date == self.today
            and reservation.status is ReservationStatus.CONFIRMED
        )
        departures = sum(
            1
            for reservation in self.reservations
            if reservation.check_out_date == self.today
            and reservation.status is ReservationStatus.CHECKED_IN
        )
        low_stock = sum(1 for item in self.inventory_items if item.is_below_minimum)

        specs: tuple[tuple[NotificationType, Priority, str, str, str | None, bool], ...] = (
            (
                NotificationType.ARRIVAL,
                Priority.HIGH,
                "Bugunku girisler",
                f"Bugun {arrivals} rezervasyon giris bekliyor.",
                "frontdesk",
                False,
            ),
            (
                NotificationType.DEPARTURE,
                Priority.NORMAL,
                "Bugunku cikislar",
                f"Bugun {departures} oda cikis yapacak.",
                "frontdesk",
                False,
            ),
            (
                NotificationType.LOW_STOCK,
                Priority.HIGH,
                "Dusuk stok uyarisi",
                f"{low_stock} stok kalemi asgari seviyenin altinda.",
                "manager",
                False,
            ),
            (
                NotificationType.MAINTENANCE,
                Priority.URGENT,
                "Oda satisa kapatildi",
                "Klima arizasi nedeniyle bir oda 3 gun satisa kapatildi.",
                "maintenance",
                False,
            ),
            (
                NotificationType.TASK,
                Priority.NORMAL,
                "Kat hizmetleri gorevleri",
                "Bugun icin bekleyen temizlik gorevleri var.",
                "housekeeping",
                True,
            ),
            (
                NotificationType.WARNING,
                Priority.HIGH,
                "Kara listede misafir",
                "Kara listeye alinmis bir misafir icin rezervasyon talebi geldi.",
                "manager",
                False,
            ),
            (
                NotificationType.INFO,
                Priority.LOW,
                "Demo verisi yuklendi",
                "Sistem demo verisiyle dolduruldu. Gercek kullanimda temizleyin.",
                None,
                True,
            ),
            (
                NotificationType.SUCCESS,
                Priority.LOW,
                "Gun sonu tamamlandi",
                "Dunun kasa kapanisi sorunsuz tamamlandi.",
                "accounting",
                True,
            ),
        )
        for index, (kind, priority, title, message, role_code, is_read) in enumerate(specs):
            user = self.users.get(role_code) if role_code else None
            self.session.add(
                Notification(
                    user_id=user.id if user else None,
                    property_id=self.hotel_property.id,
                    notification_type=kind,
                    priority=priority,
                    title=title,
                    message=message,
                    is_read=is_read,
                    read_at=_at(self.today, 8) if is_read else None,
                    action_url="reservations" if kind is NotificationType.ARRIVAL else None,
                    expires_at=_at(self.today + timedelta(days=7 + index), 23),
                )
            )
            self._bump("notification")

    def _create_audit_logs(self) -> None:
        sample_reservation = self.reservations[0] if self.reservations else None
        entries: tuple[tuple[str, AuditAction, str, str | None, int | None, bool], ...] = (
            ("frontdesk", AuditAction.LOGIN, "Kullanici giris yapti.", None, None, True),
            (
                "frontdesk",
                AuditAction.CREATE,
                "Yeni rezervasyon olusturuldu.",
                "Reservation",
                sample_reservation.id if sample_reservation else None,
                True,
            ),
            (
                "housekeeping",
                AuditAction.UPDATE,
                "Oda durumu 'temiz' olarak guncellendi.",
                "Room",
                self.rooms[0].id if self.rooms else None,
                True,
            ),
            (
                "maintenance",
                AuditAction.UPDATE,
                "Oda ariza nedeniyle satisa kapatildi.",
                "Room",
                self.rooms[-1].id if self.rooms else None,
                True,
            ),
            (
                "accounting",
                AuditAction.EXPORT,
                "Gunluk gelir raporu disa aktarildi.",
                "Report",
                None,
                True,
            ),
            (
                "housekeeping",
                AuditAction.PERMISSION_DENIED,
                "Finans modulune erisim reddedildi.",
                None,
                None,
                False,
            ),
            (
                "manager",
                AuditAction.SETTINGS_CHANGED,
                "Varsayilan KDV orani guncellendi.",
                "Setting",
                None,
                True,
            ),
            ("frontdesk", AuditAction.LOGIN_FAILED, "Hatali parola denemesi.", None, None, False),
        )
        for index, (role_code, action, description, entity, entity_id, success) in enumerate(
            entries
        ):
            user = self.users.get(role_code)
            self.session.add(
                AuditLog(
                    created_at=_at(self.today - timedelta(days=index % 5), 7 + index % 12),
                    user_id=user.id if user else None,
                    username=user.username if user else None,
                    property_id=self.hotel_property.id,
                    action=action,
                    entity_type=entity,
                    entity_id=entity_id,
                    description=description,
                    ip_address="127.0.0.1",
                    is_success=success,
                )
            )
            self._bump("audit_log")

    # ================================================================
    #  Calistirici
    # ================================================================
    def build(self) -> DemoDataSummary:
        self.create_property()
        self.create_reference_data()
        self.create_room_types()
        self.create_rooms()
        self.create_rate_plans()
        self.create_staff()
        self.create_partners()
        self.create_inventory()
        self.create_guests()
        self.create_reservations()
        self.create_operations()
        self.create_system_records()
        self.session.commit()

        return DemoDataSummary(
            seed=0,  # cagiran taraf doldurur
            scale=self.profile.name,
            reference_date=self.today,
            counts=dict(self.counts),
            users=list(self.credentials),
        )


# ==========================================================================
#  Genel API
# ==========================================================================
def create_demo_data(
    session: Session,
    *,
    seed: int = 42,
    scale: str = "medium",
) -> DemoDataSummary:
    """Tutarli, belirlenimci bir demo veri kumesi uretir.

    Parameters
    ----------
    session:
        Kayitlarin yazilacagi oturum. Islem basarili biterse **commit edilir**.
    seed:
        Rastgelelik tohumu. Ayni tohum + ayni gun = birebir ayni veri.
    scale:
        ``"small"``, ``"medium"`` veya ``"large"``.

    Raises
    ------
    ValidationError
        Bilinmeyen bir olcek adi verilirse.
    ConflictError
        Veritabaninda zaten demo verisi varsa. Once
        :func:`clear_demo_data` calistirilmalidir; aksi halde ayni kodlu
        tesis/kullanici kayitlari benzersizlik kisitlarini ihlal ederdi.
    """
    profile = SCALE_PROFILES.get(scale)
    if profile is None:
        raise ValidationError(
            f"Bilinmeyen demo olcegi: {scale}. Gecerli degerler: "
            f"{', '.join(sorted(SCALE_PROFILES))}.",
            field="scale",
        )

    existing = session.scalars(
        select(Property).where(Property.code == DEMO_PROPERTY_CODE)
    ).one_or_none()
    if existing is not None:
        raise ConflictError(
            "Veritabaninda zaten demo verisi var. Yeniden olusturmadan once "
            "mevcut demo verisini temizleyin.",
            detail=f"property.code={DEMO_PROPERTY_CODE} zaten mevcut.",
            context={"property_id": existing.id},
        )

    # Roller olmadan demo kullanicilarina yetki atanamaz; kurulum idempotenttir.
    bootstrap_security(session, create_admin=False)

    builder = _DemoBuilder(session, rng=random.Random(seed), profile=profile)
    summary = builder.build()
    summary.seed = seed

    log.info(
        "demo_veri_olusturuldu",
        olcek=scale,
        seed=seed,
        toplam_kayit=summary.total_records,
    )
    return summary


#: Silme sirasi **onemlidir**: yabanci anahtar kisitlari acikken (SQLite'ta
#: ``PRAGMA foreign_keys=ON``) cocuk kayitlar once silinmelidir. Liste
#: yukaridan asagiya "en yapraktan koke" dogru ilerler.
def clear_demo_data(session: Session, *, confirm: bool = False) -> DemoClearSummary:
    """Demo verisini siler. ``confirm=True`` verilmeden **calismaz**.

    Bu islem geri alinamaz ve gercek bir veritabaninda yanlislikla
    calistirilirsa veri kaybina yol acar. Bu yuzden onay bir varsayilan
    degil, cagiran tarafin acikca yazmasi gereken bir parametredir.

    Silinenler yalnizca demo isaretli kayitlardir:

    * ``property.code == "DEMO01"`` tesisine bagli her sey
    * ``notes == "[DEMO VERISI]"`` isaretli misafir ve kullanicilar
    * ``DEMO-`` on ekli kurumsal musteri, acente ve tedarikciler

    Referans veriler (oda ozellikleri, roller, izinler) **korunur**: bunlar
    demo verisi degil, kurulum verisidir.

    Raises
    ------
    ValidationError
        ``confirm`` verilmediginde.
    """
    if not confirm:
        raise ValidationError(
            "Demo verisini silmek icin onay gerekir. Bu islem geri alinamaz.",
            field="confirm",
            detail="clear_demo_data(confirm=True) seklinde cagirin.",
        )

    summary = DemoClearSummary()
    hotel_property = session.scalars(
        select(Property).where(Property.code == DEMO_PROPERTY_CODE)
    ).one_or_none()

    guest_ids = select(Guest.id).where(Guest.notes == DEMO_MARKER)
    user_ids = select(User.id).where(User.notes == DEMO_MARKER)

    def _run(label: str, statement) -> None:  # type: ignore[no-untyped-def]
        result = session.execute(statement)
        count = int(result.rowcount or 0)
        if count:
            summary.deleted[label] = summary.deleted.get(label, 0) + count

    if hotel_property is not None:
        pid = hotel_property.id
        room_ids = select(Room.id).where(Room.property_id == pid)
        room_type_ids = select(RoomType.id).where(RoomType.property_id == pid)
        reservation_ids = select(Reservation.id).where(Reservation.property_id == pid)
        reservation_room_ids = select(ReservationRoom.id).where(
            ReservationRoom.reservation_id.in_(reservation_ids)
        )
        folio_ids = select(Folio.id).where(Folio.property_id == pid)
        item_ids = select(InventoryItem.id).where(InventoryItem.property_id == pid)
        ticket_ids = select(MaintenanceTicket.id).where(MaintenanceTicket.property_id == pid)
        invoice_ids = select(Invoice.id).where(Invoice.property_id == pid)
        request_ids = select(PurchaseRequest.id).where(PurchaseRequest.property_id == pid)
        employee_ids = select(Employee.id).where(Employee.property_id == pid)
        building_ids = select(Building.id).where(Building.property_id == pid)
        rate_plan_ids = select(RatePlan.id).where(RatePlan.property_id == pid)

        _run(
            "minibar_consumption",
            delete(MinibarConsumption).where(MinibarConsumption.room_id.in_(room_ids)),
        )
        _run(
            "stock_movement",
            delete(StockMovement).where(StockMovement.inventory_item_id.in_(item_ids)),
        )
        _run(
            "maintenance_part",
            delete(MaintenancePart).where(MaintenancePart.ticket_id.in_(ticket_ids)),
        )
        _run(
            "maintenance_ticket",
            delete(MaintenanceTicket).where(MaintenanceTicket.property_id == pid),
        )
        _run(
            "housekeeping_task",
            delete(HousekeepingTask).where(HousekeepingTask.property_id == pid),
        )
        _run(
            "lost_and_found",
            delete(LostAndFoundItem).where(LostAndFoundItem.property_id == pid),
        )
        _run(
            "purchase_request_line",
            delete(PurchaseRequestLine).where(PurchaseRequestLine.request_id.in_(request_ids)),
        )
        _run(
            "purchase_request",
            delete(PurchaseRequest).where(PurchaseRequest.property_id == pid),
        )
        _run("inventory_item", delete(InventoryItem).where(InventoryItem.property_id == pid))
        _run("warehouse", delete(Warehouse).where(Warehouse.property_id == pid))
        _run(
            "cash_entry",
            delete(CashRegisterEntry).where(CashRegisterEntry.property_id == pid),
        )
        _run("invoice_line", delete(InvoiceLine).where(InvoiceLine.invoice_id.in_(invoice_ids)))
        _run("invoice", delete(Invoice).where(Invoice.property_id == pid))
        _run("charge", delete(Charge).where(Charge.folio_id.in_(folio_ids)))
        _run("payment", delete(Payment).where(Payment.folio_id.in_(folio_ids)))
        _run("stay", delete(Stay).where(Stay.reservation_room_id.in_(reservation_room_ids)))
        _run("folio", delete(Folio).where(Folio.property_id == pid))
        _run(
            "reservation_guest",
            delete(ReservationGuest).where(
                ReservationGuest.reservation_room_id.in_(reservation_room_ids)
            ),
        )
        _run(
            "reservation_room",
            delete(ReservationRoom).where(ReservationRoom.reservation_id.in_(reservation_ids)),
        )
        _run("waitlist", delete(WaitlistEntry).where(WaitlistEntry.property_id == pid))
        _run("reservation", delete(Reservation).where(Reservation.property_id == pid))
        _run("notification", delete(Notification).where(Notification.property_id == pid))
        _run("audit_log", delete(AuditLog).where(AuditLog.property_id == pid))
        _run("document", delete(Document).where(Document.property_id == pid))
        _run("setting", delete(Setting).where(Setting.property_id == pid))
        _run("room_photo", delete(RoomPhoto).where(RoomPhoto.room_id.in_(room_ids)))
        _run(
            "room_photo",
            delete(RoomPhoto).where(RoomPhoto.room_type_id.in_(room_type_ids)),
        )
        _run(
            "rate_plan_rate",
            delete(RatePlanRate).where(RatePlanRate.rate_plan_id.in_(rate_plan_ids)),
        )
        _run("rate_plan", delete(RatePlan).where(RatePlan.property_id == pid))
        _run("shift", delete(Shift).where(Shift.employee_id.in_(employee_ids)))
        _run("employee", delete(Employee).where(Employee.property_id == pid))
        _run("room", delete(Room).where(Room.property_id == pid))
        _run("room_type", delete(RoomType).where(RoomType.property_id == pid))
        _run("department", delete(Department).where(Department.property_id == pid))
        _run("floor", delete(Floor).where(Floor.building_id.in_(building_ids)))
        _run("building", delete(Building).where(Building.property_id == pid))
        _run("service", delete(Service).where(Service.property_id == pid))
        _run("tax_rate", delete(TaxRate).where(TaxRate.property_id == pid))

    # Tesise bagli olmayan demo kayitlari.
    _run("guest_note", delete(GuestNote).where(GuestNote.guest_id.in_(guest_ids)))
    _run(
        "guest_preference",
        delete(GuestPreference).where(GuestPreference.guest_id.in_(guest_ids)),
    )
    _run("consent", delete(ConsentRecord).where(ConsentRecord.guest_id.in_(guest_ids)))
    _run("guest", delete(Guest).where(Guest.notes == DEMO_MARKER))
    _run("company", delete(Company).where(Company.code.startswith(DEMO_CODE_PREFIX)))
    _run("agency", delete(Agency).where(Agency.code.startswith(DEMO_CODE_PREFIX)))
    _run("supplier", delete(Supplier).where(Supplier.code.startswith(DEMO_CODE_PREFIX)))
    _run("notification", delete(Notification).where(Notification.user_id.in_(user_ids)))
    _run("user_session", delete(UserSession).where(UserSession.user_id.in_(user_ids)))
    _run("user", delete(User).where(User.notes == DEMO_MARKER))

    if hotel_property is not None:
        _run("property", delete(Property).where(Property.id == hotel_property.id))

    session.commit()
    session.expunge_all()

    log.warning(
        "demo_veri_silindi",
        toplam_kayit=summary.total_deleted,
        tablo_sayisi=len(summary.deleted),
    )
    return summary


__all__ = [
    "DEMO_CODE_PREFIX",
    "DEMO_EMAIL_DOMAIN",
    "DEMO_MARKER",
    "DEMO_PHONE_MASK",
    "DEMO_PROPERTY_CODE",
    "DEMO_USERS",
    "DEMO_WARNING",
    "FIRST_NAMES",
    "SCALE_PROFILES",
    "SURNAMES",
    "DemoClearSummary",
    "DemoDataSummary",
    "DemoUserCredential",
    "DemoUserSpec",
    "ScaleProfile",
    "clear_demo_data",
    "create_demo_data",
]
