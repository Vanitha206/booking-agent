"""Tool definitions the model sees, and the dispatcher that runs them against the store.

The parent's contact (phone or email) comes from the channel the message arrived on,
never from the model, so a parent can only book, see or change their own meetings.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .store import BookingError, BookingStore


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


_STR = {"type": "string"}
_ISO = {"type": "string", "description": "Local date-time in ISO 8601, e.g. 2026-11-03T14:00:00"}
_STAFF = {"type": ["string", "null"], "description": "Staff member's name, or null for anyone who takes this meeting"}

TOOLS: list[dict] = [
    {
        "name": "list_meeting_options",
        "description": "List the meeting types the school offers and which staff take each one.",
        "input_schema": _schema({}, []),
    },
    {
        "name": "check_availability",
        "description": "List open slots for a meeting type between two date-times. Always call this before offering times.",
        "input_schema": _schema({"meeting_type": _STR, "date_from": _ISO, "date_to": _ISO, "staff": _STAFF},
                                ["meeting_type", "date_from", "date_to", "staff"]),
    },
    {
        "name": "book_meeting",
        "description": "Book a slot returned by check_availability. Sends the parent a confirmation, tells the staff "
                       "member, and schedules reminders. Only call after the parent has agreed to the exact time.",
        "input_schema": _schema(
            {"meeting_type": _STR, "start": _ISO, "staff": _STR, "parent_name": _STR, "student_name": _STR,
             "student_class": {"type": "string", "description": "Class or grade, e.g. 5A"},
             "topic": {"type": "string", "description": "What the parent wants to discuss, in a few words"},
             "attendees": {"type": "integer", "description": "How many adults will attend"}},
            ["meeting_type", "start", "staff", "parent_name", "student_name", "student_class", "topic", "attendees"],
        ),
    },
    {
        "name": "list_my_bookings",
        "description": "List this parent's upcoming meetings.",
        "input_schema": _schema({}, []),
    },
    {
        "name": "reschedule_booking",
        "description": "Move one of this parent's meetings to a new open slot from check_availability.",
        "input_schema": _schema({"booking_id": _STR, "new_start": _ISO, "staff": _STAFF},
                                ["booking_id", "new_start", "staff"]),
    },
    {
        "name": "cancel_booking",
        "description": "Cancel one of this parent's meetings. Only after the parent has clearly asked to cancel.",
        "input_schema": _schema({"booking_id": _STR, "reason": _STR}, ["booking_id", "reason"]),
    },
    {
        "name": "handoff_to_staff",
        "description": "Pass the conversation to the school office: urgent or sensitive concerns (safety, health, "
                       "bullying), requests outside policy, an unhappy parent, or repeated tool failures.",
        "input_schema": _schema({"reason": _STR, "summary": _STR}, ["reason", "summary"]),
    },
]

for _tool in TOOLS:
    _tool["strict"] = True


def _dt(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise BookingError(f"'{value}' is not an ISO 8601 date-time.")


def _booking_json(b) -> dict:
    return {"booking_id": b.id, "status": b.status, "meeting_type": b.meeting_type, "staff": b.staff,
            "start": b.start.isoformat(), "end": b.end.isoformat(), "student_name": b.student_name}


def run_tool(store: BookingStore, parent_contact: str, name: str, args: dict[str, Any]) -> str:
    """Run one tool call. Raises BookingError for rule violations, which the caller reports as is_error."""
    if name == "list_meeting_options":
        return json.dumps({
            "meeting_types": [{"name": mt.name, "minutes": mt.duration_minutes, "staff": list(mt.staff)}
                              for mt in store.meeting_types.values()],
            "staff_roles": store.staff,
        })
    if name == "check_availability":
        slots = store.check_availability(args["meeting_type"], _dt(args["date_from"]), _dt(args["date_to"]),
                                         args.get("staff"))
        return json.dumps({"slots": slots[:12], "total_open": len(slots)})
    if name == "book_meeting":
        b = store.book_meeting(args["meeting_type"], _dt(args["start"]), args["staff"], args["parent_name"],
                               parent_contact, args["student_name"], args["student_class"], args["topic"],
                               args["attendees"])
        return json.dumps({**_booking_json(b), "confirmation_sent_to": parent_contact})
    if name == "list_my_bookings":
        now = store.clock()
        mine = [b for b in store.bookings.values()
                if b.parent_contact == parent_contact and b.status == "confirmed" and b.end > now]
        return json.dumps({"bookings": [_booking_json(b) for b in sorted(mine, key=lambda b: b.start)]})
    if name == "reschedule_booking":
        b = store.reschedule_booking(args["booking_id"], parent_contact, _dt(args["new_start"]), args.get("staff"))
        return json.dumps(_booking_json(b))
    if name == "cancel_booking":
        b = store.cancel_booking(args["booking_id"], parent_contact, args.get("reason", ""))
        return json.dumps(_booking_json(b))
    if name == "handoff_to_staff":
        return json.dumps({"ticket": store.handoff(args["reason"], args["summary"])})
    raise BookingError(f"Unknown tool '{name}'.")
