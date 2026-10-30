"""Sample school data for trying the agent. Replace with the school's real staff and meeting types."""

from __future__ import annotations

from datetime import datetime, timedelta

from .store import BookingStore, MeetingType

SCHOOL_NAME = "Greenfield Public School"

STAFF = {
    "Ms. Rao": "Class 5A teacher",
    "Mr. Iyer": "Class 7B teacher",
    "Mrs. Fernandes": "Class 3C teacher",
    "Mr. Khan": "Maths teacher, classes 8 to 10",
    "Admissions Office": "New admissions and school visits",
    "Ms. Thomas": "School counsellor",
    "Dr. Menon": "Principal",
}

MEETING_TYPES = {
    "parent-teacher meeting": MeetingType("parent-teacher meeting", 20,
                                          ("Ms. Rao", "Mr. Iyer", "Mrs. Fernandes", "Mr. Khan")),
    "admissions visit": MeetingType("admissions visit", 45, ("Admissions Office",)),
    "counsellor meeting": MeetingType("counsellor meeting", 30, ("Ms. Thomas",)),
    "principal meeting": MeetingType("principal meeting", 30, ("Dr. Menon",)),
}

# Bookings other parents already hold, so availability looks like a real week.
# (days after today, hour, minute, meeting type, staff, parent, contact, student, class)
_EXISTING = [
    (1, 9, 0, "parent-teacher meeting", "Ms. Rao", "Anita Sharma", "+15550201", "Rohan Sharma", "5A"),
    (1, 9, 30, "parent-teacher meeting", "Ms. Rao", "David Joseph", "+15550202", "Maria Joseph", "5A"),
    (1, 10, 0, "admissions visit", "Admissions Office", "Kavya Nair", "+15550203", "Arjun Nair", "Nursery"),
    (1, 14, 0, "counsellor meeting", "Ms. Thomas", "Sunil Gupta", "+15550204", "Neha Gupta", "8B"),
    (2, 11, 0, "parent-teacher meeting", "Mr. Iyer", "Fatima Ali", "+15550205", "Zara Ali", "7B"),
    (2, 15, 0, "principal meeting", "Dr. Menon", "Ravi Kumar", "+15550206", "Isha Kumar", "10A"),
    (3, 8, 30, "parent-teacher meeting", "Mr. Khan", "Meera Pillai", "+15550207", "Adit Pillai", "9C"),
]


def next_school_day(start: datetime, days: int) -> datetime:
    day = start
    while days > 0:
        day += timedelta(days=1)
        if day.weekday() < 5:
            days -= 1
    return day


def sample_store(clock) -> BookingStore:
    store = BookingStore(clock=clock, staff=dict(STAFF), meeting_types=dict(MEETING_TYPES))
    today = clock().replace(hour=0, minute=0, second=0, microsecond=0)
    for days, hour, minute, mtype, staff, parent, contact, student, cls in _EXISTING:
        start = next_school_day(today, days).replace(hour=hour, minute=minute)
        store.book_meeting(mtype, start, staff, parent, contact, student, cls, "sample booking")
    store.outbox.clear()  # sample bookings shouldn't show as sent messages
    return store
