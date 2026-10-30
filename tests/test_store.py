from datetime import datetime, timedelta

import pytest

from booking_agent.store import BookingError, BookingStore

# Monday 2 November 2026, 08:00
MONDAY = datetime(2026, 11, 2, 8, 0)


@pytest.fixture
def clock():
    now = [MONDAY - timedelta(days=3)]  # Friday before
    return now


@pytest.fixture
def store(clock):
    return BookingStore(clock=lambda: clock[0])


def book(store, start, staff="Ms. Rao", contact="+1555", student="Asha", mtype="parent-teacher meeting"):
    return store.book_meeting(mtype, start, staff, "Priya", contact, student, "5A", "progress")


def test_availability_only_on_school_days_and_hours(store):
    slots = store.check_availability("parent-teacher meeting", MONDAY - timedelta(days=2), MONDAY + timedelta(hours=23))
    starts = {datetime.fromisoformat(s["start"]) for s in slots}
    assert starts, "expected Monday slots"
    assert all(s.weekday() < 5 for s in starts)
    assert min(starts).hour == 8
    assert all(datetime.fromisoformat(s["end"]).hour <= 16 for s in slots)


def test_booking_confirms_and_notifies_parent_and_staff(store):
    b = book(store, MONDAY.replace(hour=10))
    kinds = {(m.kind, m.to) for m in store.outbox}
    assert ("confirmation", "+1555") in kinds
    assert ("staff_notice", "Ms. Rao") in kinds
    assert b.end - b.start == timedelta(minutes=20)


def test_no_double_booking_of_staff(store):
    book(store, MONDAY.replace(hour=10))
    with pytest.raises(BookingError, match="just taken"):
        book(store, MONDAY.replace(hour=10, minute=10), contact="+1999", student="Ben")
    # Another teacher is still free at the same time.
    book(store, MONDAY.replace(hour=10), staff="Mr. Iyer", contact="+1999", student="Ben")


def test_booked_slot_disappears_from_availability(store):
    book(store, MONDAY.replace(hour=10))
    slots = store.check_availability("parent-teacher meeting", MONDAY, MONDAY.replace(hour=16), staff="Ms. Rao")
    assert all(not (s["start"] <= MONDAY.replace(hour=10).isoformat() < s["end"]) for s in slots)


def test_repeat_booking_request_is_idempotent(store):
    a = book(store, MONDAY.replace(hour=10))
    b = book(store, MONDAY.replace(hour=10))
    assert a.id == b.id
    assert len(store.bookings) == 1


def test_rejects_weekend_out_of_hours_and_wrong_staff(store):
    with pytest.raises(BookingError, match="school days"):
        book(store, MONDAY.replace(hour=10) - timedelta(days=1))
    with pytest.raises(BookingError, match="meeting hours"):
        book(store, MONDAY.replace(hour=15, minute=50))
    with pytest.raises(BookingError, match="does not take"):
        book(store, MONDAY.replace(hour=10), staff="Admissions Office")


def test_parent_cannot_see_or_change_another_parents_booking(store):
    b = book(store, MONDAY.replace(hour=10))
    with pytest.raises(BookingError, match="No booking"):
        store.cancel_booking(b.id, "+1999")
    assert store.bookings[b.id].status == "confirmed"


def test_reschedule_frees_old_slot_and_moves_reminders(store):
    b = book(store, MONDAY.replace(hour=10))
    store.reschedule_booking(b.id, "+1555", MONDAY.replace(hour=11))
    assert b.start.hour == 11
    assert not store._busy("Ms. Rao", MONDAY.replace(hour=10), MONDAY.replace(hour=10, minute=20))
    assert {r.send_at for r in store.reminders} == {b.start - timedelta(hours=24), b.start - timedelta(hours=2)}


def test_changes_inside_cutoff_go_to_office(store, clock):
    b = book(store, MONDAY.replace(hour=10))
    clock[0] = MONDAY.replace(hour=9)
    with pytest.raises(BookingError, match="school office"):
        store.cancel_booking(b.id, "+1555")


def test_reminders_sent_once_and_not_for_cancelled(store, clock):
    kept = book(store, MONDAY.replace(hour=10))
    dropped = book(store, MONDAY.replace(hour=11), contact="+1999", student="Ben")
    store.cancel_booking(dropped.id, "+1999")
    clock[0] = MONDAY.replace(hour=8, minute=30)
    sent = store.send_due_reminders()
    assert [m.booking_id for m in sent] == [kept.id, kept.id]  # 24 h and 2 h reminders both due
    assert store.send_due_reminders() == []


def test_sample_data_loads_and_blocks_its_slots():
    from booking_agent.sample_data import sample_store

    friday = datetime(2026, 10, 30, 7, 0)
    store = sample_store(lambda: friday)
    assert len(store.bookings) == 7 and store.outbox == []
    # Ms. Rao's 9:00 on Monday is taken by a sample booking.
    with pytest.raises(BookingError, match="just taken"):
        book(store, datetime(2026, 11, 2, 9, 0))
