"""Agent loop tests with a scripted fake client, so they run without an API key."""

from datetime import datetime, timedelta
from types import SimpleNamespace

from booking_agent.agent import BookingAgent
from booking_agent.store import BookingStore

MONDAY = datetime(2026, 11, 2, 8, 0)


def text(t):
    return SimpleNamespace(type="text", text=t)


def tool_use(id, name, input):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def make_agent(responses, contact="+1555"):
    store = BookingStore(clock=lambda: MONDAY - timedelta(days=3))
    client = FakeClient(responses)
    return BookingAgent(store, contact, school="Test School", client=client), store, client


def test_books_with_contact_from_channel_not_model():
    start = MONDAY.replace(hour=10).isoformat()
    agent, store, client = make_agent([
        SimpleNamespace(stop_reason="tool_use", content=[tool_use("t1", "book_meeting", {
            "meeting_type": "parent-teacher meeting", "start": start, "staff": "Ms. Rao", "parent_name": "Priya",
            "student_name": "Asha", "student_class": "5A", "topic": "reading", "attendees": 2})]),
        SimpleNamespace(stop_reason="end_turn", content=[text("Booked for Monday 10:00 with Ms. Rao.")]),
    ])
    assert agent.reply("Book Monday 10am with Ms. Rao") == "Booked for Monday 10:00 with Ms. Rao."
    (booking,) = store.bookings.values()
    assert booking.parent_contact == "+1555"
    # The tool result went back to the model in one user message.
    results = agent.messages[-2]["content"]
    assert results[0]["tool_use_id"] == "t1" and results[0]["is_error"] is False
    assert client.calls[0]["fallbacks"] == "default"


def test_rule_violation_returns_error_result_not_crash():
    agent, store, client = make_agent([
        SimpleNamespace(stop_reason="tool_use", content=[tool_use("t1", "cancel_booking",
                                                                  {"booking_id": "bk_9999", "reason": ""})]),
        SimpleNamespace(stop_reason="end_turn", content=[text("I couldn't find that booking.")]),
    ])
    agent.reply("cancel bk_9999")
    result = agent.messages[-2]["content"][0]
    assert result["is_error"] is True and "No booking" in result["content"]


def test_refusal_hands_off_to_office():
    agent, store, _ = make_agent([SimpleNamespace(stop_reason="refusal", content=[])])
    reply = agent.reply("hello")
    assert "school office" in reply
    assert len(store.handoffs) == 1
