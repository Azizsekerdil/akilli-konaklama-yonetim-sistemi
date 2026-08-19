"""Kat hizmetleri servisi: gunluk gorev uretimi, atama, tamamlama ve kontrol.

Gorev yasam dongusu
-------------------
``PENDING`` -> ``ASSIGNED`` -> ``IN_PROGRESS`` -> ``COMPLETED`` -> ``INSPECTED``

Kontrol adimi (:meth:`HousekeepingService.inspect`) tek yonlu degildir:
kontrol **basarisiz** olursa gorev ``PENDING``'e geri doner ve oda yeniden
``DIRTY`` isaretlenir. Bunun nedeni operasyoneldir - kotu temizlenmis bir oda
"tamamlandi" olarak kapanirsa resepsiyon o odayi satar ve misafir kirli odaya
girer. Geri donus, hatanin ekranda gorunur kalmasini saglar.

Idempotent gorev uretimi
------------------------
:meth:`HousekeepingService.generate_daily_tasks` ayni gun icinde kac kez
calistirilirsa calistirilsin ayni oda icin ikinci bir gorev uretmez. Bu
kritiktir: vardiya sefi dugmeye iki kez basarsa kat gorevlisinin listesinde
her oda iki kez gorunur, is yuku olcumu bozulur ve ayni oda iki kez
temizlenir. Mukerrerlik kontrolu ``(oda, plan tarihi)`` ciftine bakar ve
**iptal edilmis** gorevleri saymaz; iptal edilen bir gorevin yerine yenisi
uretilebilmelidir.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from sqlalchemy import select

from app.application.context import ServiceContext
from app.core.exceptions import BusinessRuleError, NotFoundError, ValidationError
from app.core.log import get_logger
from app.domain.enums import (
    UNSELLABLE_ROOM_STATUSES,
    AuditAction,
    EmploymentStatus,
    HousekeepingStatus,
    HousekeepingTaskType,
    Priority,
    RoomHousekeepingStatus,
)
from app.domain.rules.availability import Booking
from app.domain.value_objects import DateRange
from app.infrastructure.db.base import utcnow
from app.infrastructure.db.models.operations import HousekeepingTask
from app.infrastructure.db.models.organization import Department, Employee
from app.infrastructure.db.models.rooms import Room
from app.infrastructure.db.repositories import OperationsRepository, ReservationRepository
from app.security.permissions import Perm

log = get_logger(__name__)

#: Kat hizmetleri departmani icin aranan kodlar. Bulunamazsa tesisin tum
#: aktif personeli aday kabul edilir - kucuk isletmelerde departman tanimi
#: cogu zaman yapilmaz ve o durumda bos bir personel listesi gostermek
#: gorev atamayi tumuyle imkansiz kilardi.
HOUSEKEEPING_DEPARTMENT_CODES: tuple[str, ...] = ("KAT", "HOUSEKEEPING")

#: Gorev turune gore varsayilan sure (dakika) ve oncelik.
CHECKOUT_TASK_MINUTES = 45
DAILY_TASK_MINUTES = 25

#: Gorevin uzerinde islem yapilabilecegi (henuz kapanmamis) durumlar.
_OPEN_STATUSES: frozenset[HousekeepingStatus] = frozenset(
    {
        HousekeepingStatus.PENDING,
        HousekeepingStatus.ASSIGNED,
        HousekeepingStatus.IN_PROGRESS,
    }
)


class HousekeepingService:
    """Kat hizmetleri gorevleri ve oda temizlik durumu."""

    def __init__(self, context: ServiceContext) -> None:
        self.ctx = context
        self.session = context.session
        self.operations = OperationsRepository(context.session)
        self.reservations = ReservationRepository(context.session)

    # ----------------------------------------------------------------- #
    #  Listeleme
    # ----------------------------------------------------------------- #
    def daily_tasks(
        self,
        day: date | None = None,
        employee_id: int | None = None,
        status: HousekeepingStatus | None = None,
    ) -> list[HousekeepingTask]:
        """Bir gunun kat hizmetleri gorevlerini dondurur.

        ``day`` verilmezse bugun kullanilir. Siralama plan tarihi ve oda
        numarasina goredir; kat gorevlisi listesi bu sirayla basilir.
        """
        self.ctx.require(Perm.HOUSEKEEPING_VIEW)
        property_id = self.ctx.require_property()
        return self.operations.housekeeping_tasks(
            property_id,
            day=day or utcnow().date(),
            status=status,
            employee_id=employee_id,
        )

    def staff(self) -> list[Employee]:
        """Gorev atanabilecek aktif personel.

        Kat hizmetleri departmani tanimliysa yalnizca o departman, degilse
        tesisin tum aktif personeli dondurulur (bkz.
        :data:`HOUSEKEEPING_DEPARTMENT_CODES`).
        """
        self.ctx.require(Perm.HOUSEKEEPING_VIEW)
        property_id = self.ctx.require_property()

        stmt = select(Employee).where(
            Employee.property_id == property_id,
            Employee.employment_status == EmploymentStatus.ACTIVE,
        )
        department_ids = list(
            self.session.scalars(
                select(Department.id).where(
                    Department.property_id == property_id,
                    Department.code.in_(HOUSEKEEPING_DEPARTMENT_CODES),
                )
            ).all()
        )
        if department_ids:
            stmt = stmt.where(Employee.department_id.in_(department_ids))
        return list(
            self.session.scalars(stmt.order_by(Employee.last_name, Employee.first_name)).all()
        )

    # ----------------------------------------------------------------- #
    #  Gunluk gorev uretimi
    # ----------------------------------------------------------------- #
    def generate_daily_tasks(self, day: date | None = None) -> list[HousekeepingTask]:
        """Gunun temizlik gorevlerini uretir - **idempotent**.

        Iki kaynak taranir:

        * O gun **cikis** yapacak odalar -> :attr:`HousekeepingTaskType.CHECKOUT_CLEANING`
          (yuksek oncelik; oda ayni gun yeniden satilabilir).
        * O gun **otelde kalmaya devam eden** odalar ->
          :attr:`HousekeepingTaskType.DAILY_CLEANING`.

        Iki kume yari acik aralik semantigi geregi kesismez: cikis gunu
        misafir artik "otelde" sayilmaz. Yine de kesisim savunma amacli
        dislanir; ayni odaya hem cikis hem gunluk temizlik yazilmasi kat
        gorevlisinin listesini bozardi.

        Satisa kapali (servis disi / arizali) odalar atlanir - onlarin isi
        kat hizmetlerinde degil teknik serviste.

        Returns
        -------
        list[HousekeepingTask]
            **Bu cagrida** olusturulan gorevler. Ikinci calistirmada bos
            liste doner; cagiran taraf "0 gorev uretildi" mesajini bundan
            uretir.
        """
        self.ctx.require(Perm.HOUSEKEEPING_ASSIGN)
        property_id = self.ctx.require_property()
        target_day = day or utcnow().date()

        departing = {
            row.room_id
            for row in self.reservations.departures_on(property_id, target_day)
            if row.room_id is not None
        }
        staying = {
            row.room_id
            for row in self.reservations.in_house_on(property_id, target_day)
            if row.room_id is not None
        } - departing

        # Mukerrerlik kalkani: o gun icin zaten gorevi olan odalar.
        # Iptal edilmis gorevler sayilmaz; iptal edilenin yerine yenisi
        # uretilebilmelidir.
        already_planned = set(
            self.session.scalars(
                select(HousekeepingTask.room_id).where(
                    HousekeepingTask.property_id == property_id,
                    HousekeepingTask.scheduled_date == target_day,
                    HousekeepingTask.status != HousekeepingStatus.CANCELLED,
                )
            ).all()
        )
        blocked_rooms = set(
            self.session.scalars(
                select(Room.id).where(
                    Room.property_id == property_id,
                    Room.housekeeping_status.in_(list(UNSELLABLE_ROOM_STATUSES)),
                )
            ).all()
        )

        plan: list[tuple[int, HousekeepingTaskType, Priority, int]] = [
            (room_id, HousekeepingTaskType.CHECKOUT_CLEANING, Priority.HIGH, CHECKOUT_TASK_MINUTES)
            for room_id in sorted(departing)
        ]
        plan += [
            (room_id, HousekeepingTaskType.DAILY_CLEANING, Priority.NORMAL, DAILY_TASK_MINUTES)
            for room_id in sorted(staying)
        ]

        created: list[HousekeepingTask] = []
        for room_id, task_type, priority, minutes in plan:
            if room_id in already_planned or room_id in blocked_rooms:
                continue
            task = HousekeepingTask(
                property_id=property_id,
                room_id=room_id,
                task_type=task_type,
                status=HousekeepingStatus.PENDING,
                priority=priority,
                scheduled_date=target_day,
                estimated_minutes=minutes,
            )
            self.session.add(task)
            # Ayni cagri icinde de mukerrerlik olusmasin (bir oda iki
            # rezervasyon satiriyla listede gorunebilir).
            already_planned.add(room_id)
            created.append(task)

        self.session.flush()

        self.ctx.audit(
            AuditAction.CREATE,
            f"{target_day.isoformat()} icin {len(created)} kat hizmetleri gorevi uretildi.",
            entity_type="HousekeepingTask",
            after={"day": target_day.isoformat(), "created": len(created)},
        )
        log.info("kat_hizmetleri_gorev_uretildi", day=target_day.isoformat(), count=len(created))
        return created

    # ----------------------------------------------------------------- #
    #  Gorev islemleri
    # ----------------------------------------------------------------- #
    def assign(self, task_id: int, employee_id: int) -> HousekeepingTask:
        """Gorevi bir kat gorevlisine atar."""
        self.ctx.require(Perm.HOUSEKEEPING_ASSIGN)
        task = self._get_task(task_id)
        self._require_open(task, "Kapanmis bir goreve personel atanamaz.")

        employee = self.session.get(Employee, employee_id)
        if employee is None:
            raise NotFoundError("Personel", employee_id)
        if employee.property_id != task.property_id:
            raise ValidationError(
                "Personel bu tesise bagli degil.",
                field="employee_id",
            )
        if not employee.is_available:
            raise BusinessRuleError(
                f"{employee.full_name} su anda gorev alamaz "
                f"({employee.employment_status.label}).",
                code="employee_unavailable",
            )

        before = {"employee_id": task.assigned_employee_id, "status": task.status.value}
        # Yalnizca yabanci anahtari yazmak yetmez: ``task.assigned_employee``
        # iliskisi daha once yuklendiyse BAYAT kalir ve ayni oturumda gorevi
        # okuyan ekran "Atanmadi" gostermeye devam eder. Iliskiyi atamak hem
        # nesne grafigini hem de yabanci anahtari gunceller.
        task.assigned_employee = employee
        if task.status is HousekeepingStatus.PENDING:
            task.status = HousekeepingStatus.ASSIGNED
        self.session.flush()

        self.ctx.audit(
            AuditAction.UPDATE,
            f"{self._room_label(task)} temizlik gorevi {employee.full_name} kisisine atandi.",
            entity_type="HousekeepingTask",
            entity_id=task.id,
            before=before,
            after={"employee_id": employee.id, "status": task.status.value},
        )
        return task

    def start(self, task_id: int) -> HousekeepingTask:
        """Temizligi baslatir; oda "temizleniyor" olarak isaretlenir."""
        self.ctx.require(Perm.HOUSEKEEPING_COMPLETE)
        task = self._get_task(task_id)
        self._require_open(task, "Kapanmis bir gorev yeniden baslatilamaz.")

        if task.status is HousekeepingStatus.IN_PROGRESS:
            raise BusinessRuleError("Bu gorev zaten devam ediyor.", code="task_already_started")

        task.status = HousekeepingStatus.IN_PROGRESS
        task.started_at = utcnow()

        room = self._room_of(task)
        if room is not None and room.housekeeping_status not in UNSELLABLE_ROOM_STATUSES:
            room.housekeeping_status = RoomHousekeepingStatus.CLEANING_IN_PROGRESS
        self.session.flush()

        self.ctx.audit(
            AuditAction.UPDATE,
            f"{self._room_label(task)} temizligi baslatildi.",
            entity_type="HousekeepingTask",
            entity_id=task.id,
            after={"status": task.status.value},
        )
        return task

    def complete(
        self,
        task_id: int,
        actual_minutes: int | None = None,
        issues: str | None = None,
    ) -> HousekeepingTask:
        """Temizligi tamamlar ve odayi **temiz** isaretler.

        ``actual_minutes`` verilmezse ve gorev :meth:`start` ile
        baslatilmissa sure baslangic/bitis damgalarindan hesaplanir; boylece
        personel sure girmeyi unuttugunda is yuku olcumu tumuyle kaybolmaz.
        """
        self.ctx.require(Perm.HOUSEKEEPING_COMPLETE)
        task = self._get_task(task_id)
        self._require_open(task, "Bu gorev zaten kapanmis.")

        if actual_minutes is not None and actual_minutes < 0:
            raise ValidationError("Sure negatif olamaz.", field="actual_minutes")

        now = utcnow()
        task.status = HousekeepingStatus.COMPLETED
        task.completed_at = now
        if actual_minutes is not None:
            task.actual_minutes = actual_minutes
        elif task.started_at is not None:
            task.actual_minutes = max(int((now - task.started_at).total_seconds() // 60), 0)
        if issues and issues.strip():
            task.issues_found = issues.strip()

        room = self._room_of(task)
        if room is not None and room.housekeeping_status not in UNSELLABLE_ROOM_STATUSES:
            room.housekeeping_status = RoomHousekeepingStatus.CLEAN
        self.session.flush()

        self.ctx.audit(
            AuditAction.UPDATE,
            f"{self._room_label(task)} temizligi tamamlandi.",
            entity_type="HousekeepingTask",
            entity_id=task.id,
            after={
                "status": task.status.value,
                "actual_minutes": task.actual_minutes,
                "issues": task.issues_found,
            },
        )
        return task

    def inspect(
        self,
        task_id: int,
        passed: bool,
        notes: str | None = None,
    ) -> HousekeepingTask:
        """Temizligi kontrol eder.

        ``passed=False`` durumunda gorev **yeniden acilir** (``PENDING``) ve
        oda ``DIRTY``'ye doner. Kontrolu gecmeyen bir odayi "tamamlandi"
        birakmak, resepsiyonun o odayi satmasina ve misafirin kirli odaya
        girmesine yol acar.
        """
        self.ctx.require(Perm.HOUSEKEEPING_INSPECT)
        task = self._get_task(task_id)

        if task.status is not HousekeepingStatus.COMPLETED:
            raise BusinessRuleError(
                "Yalnizca tamamlanmis bir gorev kontrol edilebilir.",
                code="task_not_completed",
                context={"status": task.status.value},
            )

        now = utcnow()
        task.inspected_at = now
        task.inspection_passed = passed
        task.inspected_by_employee_id = self._current_employee_id()
        if notes and notes.strip():
            task.issues_found = notes.strip()

        room = self._room_of(task)
        if passed:
            task.status = HousekeepingStatus.INSPECTED
            if room is not None and room.housekeeping_status not in UNSELLABLE_ROOM_STATUSES:
                room.housekeeping_status = RoomHousekeepingStatus.INSPECTED
        else:
            # Gorev yeniden acilir. Baslangic/bitis damgalari temizlenir ki
            # ikinci temizligin suresi birincininkiyle karismasin.
            task.status = HousekeepingStatus.PENDING
            task.started_at = None
            task.completed_at = None
            task.actual_minutes = None
            task.priority = Priority.HIGH
            if room is not None and room.housekeeping_status not in UNSELLABLE_ROOM_STATUSES:
                room.housekeeping_status = RoomHousekeepingStatus.DIRTY
        self.session.flush()

        self.ctx.audit(
            AuditAction.UPDATE,
            f"{self._room_label(task)} temizlik kontrolu: "
            f"{'gecti' if passed else 'kaldi - gorev yeniden acildi'}.",
            entity_type="HousekeepingTask",
            entity_id=task.id,
            after={"status": task.status.value, "passed": passed, "notes": task.issues_found},
            is_success=passed,
        )
        if not passed:
            log.warning(
                "temizlik_kontrolu_basarisiz",
                task_id=task.id,
                room=self._room_label(task),
            )
        return task

    # ----------------------------------------------------------------- #
    #  Oda durumu
    # ----------------------------------------------------------------- #
    def set_room_status(
        self,
        room_id: int,
        status: RoomHousekeepingStatus,
        *,
        force: bool = False,
    ) -> Room:
        """Odanin temizlik/servis durumunu elle degistirir.

        Oda satilabilir bir duruma dondurulurken ``out_of_service_*`` alanlari
        temizlenir. Temizlenmezse oda "temiz" gorunur ama musaitlik hesabi
        (:meth:`RoomRepository.blocks_for_range`) eski blok tarihlerini okumaya
        devam eder ve oda satilamaz - ekranla gercek arasinda sessiz bir
        tutarsizlik olusur.

        Satilmis odayi kapatma korumasi
        -------------------------------
        Oda **satilamaz** bir duruma (servis disi / arizali) alinirken o gece
        odada aktif bir rezervasyon varsa islem durdurulur. Ayni koruma
        :meth:`MaintenanceService.create_ticket` yolunda vardi; bu metotta
        yoktu ve oda planindan sag tikla "Servis disi yap" diyen bir kullanici
        satilmis bir odayi sessizce kapatabiliyordu. Misafir giris gunu kapida
        kalir.

        Neden yalnizca **bir gece**?
        ``create_ticket`` blokenin baslangic/bitis tarihlerini bilir ve o
        pencereyi tarar. Burada tarih yoktur - durum "su andan itibaren"
        gecerlidir. Ileriye dogru bir yil taramak neredeyse her odayi
        kapatilamaz yapardi (her odanin er gec bir rezervasyonu vardir) ve
        koruma kullanilamaz hale gelirdi. Bugunku gece penceresi, gercek ve
        yakin zarari - bu gece gelecek ya da halen iceride olan misafiri -
        yakalar.

        Parameters
        ----------
        force:
            Cakisma uyarisini asar; :data:`Perm.RESERVATION_OVERRIDE` ister.

        Raises
        ------
        BusinessRuleError
            Oda kapatilirken cakisan rezervasyon varsa ve ``force=False`` ise
            (``code="room_has_reservation"``).
        """
        self.ctx.require(Perm.ROOM_STATUS_CHANGE)
        property_id = self.ctx.require_property()

        room = self.session.get(Room, room_id)
        if room is None:
            raise NotFoundError("Oda", room_id)
        if room.property_id != property_id:
            raise ValidationError("Oda bu tesise ait degil.", field="room_id")

        conflicts: list[Booking] = []
        going_unsellable = (
            status in UNSELLABLE_ROOM_STATUSES
            and room.housekeeping_status not in UNSELLABLE_ROOM_STATUSES
        )
        if going_unsellable:
            conflicts = self._conflicting_bookings_tonight(room.id)
            if conflicts and not force:
                raise BusinessRuleError(
                    self._conflict_message(room, conflicts),
                    code="room_has_reservation",
                    detail=f"{len(conflicts)} cakisan rezervasyon bulundu.",
                    context={
                        "cozum": (
                            "Once misafiri baska bir odaya alin ya da yetkili onayiyla "
                            "devam edin."
                        ),
                        "room_id": room.id,
                        "conflict_count": len(conflicts),
                    },
                )
            if conflicts:
                # Bilincli asim: ayri yetki + kalici iz.
                self.ctx.require(Perm.RESERVATION_OVERRIDE)

        before = {"housekeeping_status": room.housekeeping_status.value}
        room.housekeeping_status = status
        if status not in UNSELLABLE_ROOM_STATUSES:
            room.out_of_service_from = None
            room.out_of_service_until = None
            room.out_of_service_reason = None
        self.session.flush()

        self.ctx.audit(
            AuditAction.UPDATE,
            f"{room.number} numarali odanin durumu '{status.label}' yapildi.",
            entity_type="Room",
            entity_id=room.id,
            before=before,
            after={"housekeeping_status": status.value, "forced": bool(conflicts)},
        )
        if conflicts:
            log.warning(
                "satilmis_oda_kapatildi",
                room=room.number,
                status=status.value,
                conflicts=[booking.confirmation_number for booking in conflicts],
            )
        return room

    def _conflicting_bookings_tonight(self, room_id: int) -> list[Booking]:
        """Odada **bu gece** envanteri bloke eden rezervasyonlar."""
        today = utcnow().date()
        return self.reservations.bookings_for_room(
            room_id, DateRange(today, today + timedelta(days=1))
        )

    @staticmethod
    def _conflict_message(room: Room, conflicts: Sequence[Booking]) -> str:
        first = conflicts[0]
        reference = first.confirmation_number or f"#{first.reservation_id}"
        extra = f" (+{len(conflicts) - 1} kayit daha)" if len(conflicts) > 1 else ""
        return (
            f"{room.number} numarali odada {first.date_range.format()} tarihlerinde "
            f"{reference} numarali rezervasyon var{extra}. "
            "Oda satisa kapatilirsa misafir kapida kalir."
        )

    # ----------------------------------------------------------------- #
    #  Yardimcilar
    # ----------------------------------------------------------------- #
    def _get_task(self, task_id: int) -> HousekeepingTask:
        task = self.session.get(HousekeepingTask, task_id)
        if task is None:
            raise NotFoundError("Kat hizmetleri gorevi", task_id)
        return task

    @staticmethod
    def _require_open(task: HousekeepingTask, message: str) -> None:
        if task.status not in _OPEN_STATUSES:
            raise BusinessRuleError(
                message,
                code="task_closed",
                context={"status": task.status.value},
            )

    def _room_of(self, task: HousekeepingTask) -> Room | None:
        return self.session.get(Room, task.room_id)

    def _room_label(self, task: HousekeepingTask) -> str:
        room = self._room_of(task)
        return f"{room.number} numarali oda" if room is not None else f"#{task.room_id}"

    def _current_employee_id(self) -> int | None:
        """Islemi yapan kullaniciya bagli personel kaydi (varsa).

        Her kullanicinin personel karti olmak zorunda degildir; bulunamazsa
        ``None`` doner ve kontrol kaydi personelsiz yazilir.
        """
        user_id = self.ctx.user_id
        if user_id is None:
            return None
        return self.session.scalars(select(Employee.id).where(Employee.user_id == user_id)).first()


__all__ = [
    "CHECKOUT_TASK_MINUTES",
    "DAILY_TASK_MINUTES",
    "HOUSEKEEPING_DEPARTMENT_CODES",
    "HousekeepingService",
]
