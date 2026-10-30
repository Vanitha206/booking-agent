"""Chat with the agent in a terminal, against the mock school calendar.

Commands: /outbox (messages sent), /bookings, /handoffs, /advance <hours> (move the clock and
send due reminders), /quit.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

from .agent import BookingAgent
from .sample_data import SCHOOL_NAME, sample_store


def main() -> None:
    now = [datetime.now().replace(second=0, microsecond=0)]
    store = sample_store(lambda: now[0])
    contact = sys.argv[1] if len(sys.argv) > 1 else "+15550100"
    agent = BookingAgent(store, parent_contact=contact, school=SCHOOL_NAME)
    print(f"Chatting as parent {contact}. Type /quit to exit.")
    while True:
        try:
            text = input("\nparent> ").strip()
        except EOFError:
            break
        if not text:
            continue
        if text == "/quit":
            break
        if text == "/outbox":
            for m in store.outbox:
                print(f"  [{m.sent_at:%d %b %H:%M}] {m.kind} -> {m.to}: {m.body}")
        elif text == "/bookings":
            for b in store.bookings.values():
                print(f"  {b.id} {b.status} {b.meeting_type} with {b.staff} {b.start:%a %d %b %H:%M}")
        elif text == "/handoffs":
            for h in store.handoffs:
                print(f"  {h['id']}: {h['reason']}")
        elif text.startswith("/advance"):
            hours = float(text.split()[1]) if len(text.split()) > 1 else 1
            now[0] += timedelta(hours=hours)
            for m in store.send_due_reminders():
                print(f"  reminder -> {m.to}: {m.body}")
            print(f"  clock is now {now[0]:%a %d %b %H:%M}")
        else:
            print(f"\nagent> {agent.reply(text)}")


if __name__ == "__main__":
    main()
