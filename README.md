# booking-agent

A Claude-powered assistant that lets parents book, move and cancel meetings with school staff
(class teachers, the admissions office, the school counsellor), sends confirmations, tells the
staff member, and sends reminders before each meeting.

This is the phase 1 prototype: the calendar and messaging are in-memory mocks, so it runs
anywhere. Real calendar and SMS/email/WhatsApp connections come in later phases.

## How it works

- `booking_agent/store.py` holds the school rules: staff can't be double-booked, meetings only on
  school days within meeting hours, changes close to the meeting go to the office, and a parent can
  only see or change their own bookings.
- `booking_agent/tools.py` defines the tools the model can call. The parent's phone or email comes
  from the channel the message arrived on, never from the model.
- `booking_agent/sample_data.py` has sample staff, meeting types and existing bookings for testing.
- `booking_agent/agent.py` runs the Claude tool-use loop for each parent message. Rule violations
  come back to the model as tool errors, and refusals or runaway loops hand off to the school office.

## Try it

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # or sign in with `ant auth login`
python -m booking_agent.cli +15550100
```

In the chat, `/outbox` shows messages sent, `/bookings` lists bookings, `/advance 24` moves the
clock forward and sends any reminders that are due, and `/handoffs` shows what went to the office.

Settings: `BOOKING_AGENT_MODEL` (default `claude-opus-5-5`) and `BOOKING_AGENT_EFFORT` (default `low`).

## Tests

```bash
python -m pytest
```

The tests cover the school rules and the agent loop with a scripted fake client, so they need no API key.
