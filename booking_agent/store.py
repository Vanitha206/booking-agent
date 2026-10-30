"""In-memory bookings store for parent meetings with school staff (mock calendar and messaging).

All school rules live here, not in the model: a staff member cannot be double-booked,
meetings only happen during school meeting hours, and late changes go to the office.
The agent's tools are thin wrappers over these methods, so a model mistake cannot
break the rules.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable


class BookingError(Exception):
    """A request that breaks a school rule. The message is safe to show the model."""


@dataclass(frozen=True)
class MeetingType:
    name: str
    duration_minutes: int
    staff: tuple[str, ...]  # who can take this kind of meeting


@dataclass
class Policy:
    meeting_start_hour: int = 8
    meeting_end_hour: int = 16
    slot_step_minutes: int = 15
    meeting_days: tuple[int, ...] = (0, 1, 2, 3, 4)  # Monday to Friday
    # Parents can change or cancel up to this many hours before; after that the office handles it.
    change_cutoff_hours: int = 2
    reminder_offsets_hours: tuple[int, ...] = (24, 2)
    max_attendees: int = 4


@dataclass
class Booking:
    id: str
    meeting_type: str
    staff: str
    start: datetime
    end: datetime
    parent_name: str
    parent_contact: str
    student_name: str
    student_class: str
    topic: str
    attendees: int = 1
    status: str = "confirmed"  # confirmed | cancelled


@dataclass
class Message:
    to: str
    kind: str  # confirmation | reminder | update | staff_notice
    body: str
    sent_at: datetime
    booking_id: str


@dataclass
class Reminder:
    booking_id: str
    send_at: datetime
    sent: bool = False


DEFAULT_STAFF = {
    "Ms. Rao": "Class 5A teacher",
    "Mr. Iyer": "Class 7B teacher",
    "Admissions Office": "New admissions and school visits",
    "Ms. Thomas": "School counsellor",
}

DEFAULT_MEETING_TYPES = {
    "parent-teacher meeting": MeetingType("parent-teacher meeting", 20, ("Ms. Rao", "Mr. Iyer")),
    "admissions visit": MeetingType("admissions visit", 45, ("Admissions Office",)),
    "counsellor meeting": MeetingType("counsellor meeting", 30, ("Ms. Thomas",)),
}


@dataclass
class BookingStore:
    """Holds every booking and outgoing message for one school."""

    clock: Callable[[], datetime]
    staff: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_STAFF))
    meeting_types: dict[str, MeetingType] = field(default_factory=lambda: dict(DEFAULT_MEETING_TYPES))
    policy: Policy = field(default_factory=Policy)
    bookings: dict[str, Booking] = field(default_factory=dict)
    reminders: list[Reminder] = field(default_factory=list)
    outbox: list[Message] = field(default_factory=list)
    handoffs: list[dict] = field(default_factory=list)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}_{next(self._ids):04d}"

    def _meeting_type(self, name: str) -> MeetingType:
        try:
            return self.meeting_types[name]
        except KeyError:
            raise BookingError(f"Unknown meeting type '{name}'. Offered: {', '.join(self.meeting_types)}.")

    def _staff_for(self, mt: MeetingType, staff: str | None) -> tuple[str, ...]:
        if staff is None:
            return mt.staff
        if staff not in mt.staff:
            raise BookingError(f"{staff} does not take {mt.name}s. Available: {', '.join(mt.staff)}.")
        return (staff,)

    # ---- availability -------------------------------------------------

    def _busy(self, staff: str, start: datetime, end: datetime, ignore: str | None = None) -> bool:
        return any(
            b.status == "confirmed" and b.id != ignore and b.staff == staff and b.start < end and start < b.end
            for b in self.bookings.values()
        )

    def _check_time(self, start: datetime, end: datetime) -> None:
        if start < self.clock():
            raise BookingError("That time is in the past.")
        if start.weekday() not in self.policy.meeting_days:
            raise BookingError("Meetings are only held on school days.")
        if start.hour < self.policy.meeting_start_hour or end > start.replace(
                hour=self.policy.meeting_end_hour, minute=0, second=0, microsecond=0):
            raise BookingError("That time is outside meeting hours.")

    def check_availability(self, meeting_type: str, date_from: datetime, date_to: datetime,
                           staff: str | None = None) -> list[dict]:
        mt = self._meeting_type(meeting_type)
        candidates = self._staff_for(mt, staff)
        now = self.clock()
        step = timedelta(minutes=self.policy.slot_step_minutes)
        length = timedelta(minutes=mt.duration_minutes)
        slots = []
        day = date_from.replace(hour=0, minute=0, second=0, microsecond=0)
        while day <= date_to:
            if day.weekday() in self.policy.meeting_days:
                t = day.replace(hour=self.policy.meeting_start_hour)
                close = day.replace(hour=self.policy.meeting_end_hour)
                while t + length <= close:
                    if max(now, date_from) <= t <= date_to:
                        for s in candidates:
                            if not self._busy(s, t, t + length):
                                slots.append({"start": t.isoformat(), "end": (t + length).isoformat(), "staff": s})
                    t += step
            day += timedelta(days=1)
        return slots

    # ---- booking ------------------------------------------------------

    def book_meeting(self, meeting_type: str, start: datetime, staff: str, parent_name: str,
                     parent_contact: str, student_name: str, student_class: str, topic: str,
                     attendees: int = 1) -> Booking:
        mt = self._meeting_type(meeting_type)
        self._staff_for(mt, staff)
        if not 1 <= attendees <= self.policy.max_attendees:
            raise BookingError(f"Meetings allow 1 to {self.policy.max_attendees} attendees.")
        end = start + timedelta(minutes=mt.duration_minutes)
        self._check_time(start, end)
        # Same parent, same student, same type, same time: return the existing booking (safe retry).
        for b in self.bookings.values():
            if (b.status == "confirmed" and b.meeting_type == meeting_type and b.start == start
                    and b.staff == staff and b.parent_contact == parent_contact and b.student_name == student_name):
                return b
        if self._busy(staff, start, end):
            raise BookingError("That slot was just taken. Check availability again.")
        booking = Booking(
            id=self._next_id("bk"), meeting_type=meeting_type, staff=staff, start=start, end=end,
            parent_name=parent_name, parent_contact=parent_contact, student_name=student_name,
            student_class=student_class, topic=topic, attendees=attendees,
        )
        self.bookings[booking.id] = booking
        self._send(booking, booking.parent_contact, "confirmation",
                   f"Dear {booking.parent_name}, your {booking.meeting_type} with {booking.staff} about "
                   f"{booking.student_name} is confirmed for {booking.start:%a %d %b at %H:%M}. Ref {booking.id}.")
        self._send(booking, booking.staff, "staff_notice",
                   f"New {booking.meeting_type}: {booking.parent_name} (parent of {booking.student_name}, "
                   f"{booking.student_class}) on {booking.start:%a %d %b at %H:%M}. Topic: {booking.topic}.")
        self._schedule_reminders(booking)
        return booking

    def _send(self, booking: Booking, to: str, kind: str, body: str) -> None:
        self.outbox.append(Message(to, kind, body, self.clock(), booking.id))

    def _schedule_reminders(self, booking: Booking) -> None:
        now = self.clock()
        self.reminders = [r for r in self.reminders if r.booking_id != booking.id or r.sent]
        for hours in self.policy.reminder_offsets_hours:
            send_at = booking.start - timedelta(hours=hours)
            if send_at > now:
                self.reminders.append(Reminder(booking.id, send_at))

    def send_due_reminders(self) -> list[Message]:
        """Run by the scheduler, outside any conversation."""
        now = self.clock()
        sent = []
        for r in self.reminders:
            booking = self.bookings[r.booking_id]
            if r.sent or r.send_at > now or booking.status != "confirmed":
                continue
            r.sent = True
            self._send(booking, booking.parent_contact, "reminder",
                       f"Reminder: your {booking.meeting_type} with {booking.staff} is on "
                       f"{booking.start:%a %d %b at %H:%M}. Reply CHANGE to reschedule or CANCEL to cancel.")
            sent.append(self.outbox[-1])
        return sent

    # ---- changes ------------------------------------------------------

    def get_booking(self, booking_id: str, parent_contact: str) -> Booking:
        booking = self.bookings.get(booking_id)
        # A parent can only see their own bookings.
        if booking is None or booking.parent_contact != parent_contact:
            raise BookingError(f"No booking '{booking_id}' for this contact.")
        return booking

    def _check_cutoff(self, booking: Booking) -> None:
        if booking.status != "confirmed":
            raise BookingError("This booking is already cancelled.")
        if booking.start - self.clock() < timedelta(hours=self.policy.change_cutoff_hours):
            raise BookingError(
                f"Changes within {self.policy.change_cutoff_hours} hours of the meeting go through the school "
                "office. Use handoff_to_staff."
            )

    def cancel_booking(self, booking_id: str, parent_contact: str, reason: str = "") -> Booking:
        booking = self.get_booking(booking_id, parent_contact)
        self._check_cutoff(booking)
        booking.status = "cancelled"
        self._send(booking, booking.parent_contact, "update", f"Your meeting {booking.id} is cancelled.")
        self._send(booking, booking.staff, "staff_notice",
                   f"Cancelled: {booking.meeting_type} with {booking.parent_name} on "
                   f"{booking.start:%a %d %b at %H:%M}." + (f" Reason: {reason}" if reason else ""))
        return booking

    def reschedule_booking(self, booking_id: str, parent_contact: str, new_start: datetime,
                           staff: str | None = None) -> Booking:
        booking = self.get_booking(booking_id, parent_contact)
        self._check_cutoff(booking)
        mt = self._meeting_type(booking.meeting_type)
        new_staff = staff or booking.staff
        self._staff_for(mt, new_staff)
        new_end = new_start + timedelta(minutes=mt.duration_minutes)
        self._check_time(new_start, new_end)
        if self._busy(new_staff, new_start, new_end, ignore=booking.id):
            raise BookingError("That new slot is taken. Check availability again.")
        old = booking.start
        booking.start, booking.end, booking.staff = new_start, new_end, new_staff
        self._schedule_reminders(booking)
        self._send(booking, booking.parent_contact, "update",
                   f"Your meeting {booking.id} has moved to {booking.start:%a %d %b at %H:%M} with {booking.staff}.")
        self._send(booking, booking.staff, "staff_notice",
                   f"Moved: {booking.meeting_type} with {booking.parent_name} from {old:%a %d %b %H:%M} "
                   f"to {booking.start:%a %d %b at %H:%M}.")
        return booking

    def handoff(self, reason: str, summary: str) -> str:
        ticket = self._next_id("ticket")
        self.handoffs.append({"id": ticket, "reason": reason, "summary": summary, "at": self.clock()})
        return ticket
