"""The conversation agent: one Claude tool-use loop per parent message."""

from __future__ import annotations

import json
import os

import anthropic

from .store import BookingError, BookingStore
from .tools import TOOLS, run_tool

MODEL = os.environ.get("BOOKING_AGENT_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("BOOKING_AGENT_EFFORT", "low")
MAX_TOOL_ROUNDS = 10

SYSTEM_PROMPT = """You are the meeting booking assistant for {school}. Parents message you to book, \
move or cancel meetings with school staff: class teachers, the admissions office and the school counsellor.

How to work:
- Find out who the meeting is with or what it is about, the student's name and class, and when suits the parent.
- Always check availability before offering times, and offer two or three options rather than a long list.
- Book only after the parent has agreed to one exact time. Repeat the day, time and staff member back to them.
- Before cancelling or moving a meeting, confirm which meeting the parent means.
- If a tool returns an error, explain it simply and offer the next step. Do not invent slots or bookings.
- Hand off to the school office for anything urgent or sensitive (safety, health, bullying, a complaint), \
anything the tools cannot do, or if the parent asks for a person. Tell the parent the office will follow up.
- Do not share information about other students, parents or staff schedules beyond open slots.

Write short, warm, plain messages suitable for SMS or chat. No markdown."""


class BookingAgent:
    """One conversation with one parent. The parent's contact comes from the channel, not the model."""

    def __init__(self, store: BookingStore, parent_contact: str, school: str = "the school",
                 client: anthropic.Anthropic | None = None):
        self.store = store
        self.parent_contact = parent_contact
        self.client = client or anthropic.Anthropic()
        now = store.clock()
        self.system = [
            {"type": "text", "text": SYSTEM_PROMPT.format(school=school)},
            {"type": "text", "text": f"Current local date and time: {now:%A %d %B %Y, %H:%M}."},
        ]
        self.messages: list[dict] = []
        self.log: list[dict] = []  # audit trail of every tool call

    def _call_tool(self, block) -> dict:
        try:
            result = run_tool(self.store, self.parent_contact, block.name, block.input)
            is_error = False
        except BookingError as e:
            result, is_error = str(e), True
        except (KeyError, TypeError, ValueError) as e:
            result, is_error = f"Invalid input: {e}", True
        self.log.append({"tool": block.name, "input": block.input, "result": result, "is_error": is_error})
        return {"type": "tool_result", "tool_use_id": block.id, "content": result, "is_error": is_error}

    def reply(self, text: str) -> str:
        self.messages.append({"role": "user", "content": text})
        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=self.system,
                tools=TOOLS,
                messages=self.messages,
                output_config={"effort": EFFORT},
                cache_control={"type": "ephemeral"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            # Keep the full content (including thinking blocks) so the history stays valid.
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                return self._handoff_reply("The assistant could not help with this request.")
            if response.stop_reason == "tool_use":
                results = [self._call_tool(b) for b in response.content if b.type == "tool_use"]
                self.messages.append({"role": "user", "content": results})
                continue
            return "".join(b.text for b in response.content if b.type == "text").strip()
        return self._handoff_reply("The assistant reached its step limit.")

    def _handoff_reply(self, reason: str) -> str:
        transcript = json.dumps(self.log[-5:], default=str)
        ticket = self.store.handoff(reason, f"Parent {self.parent_contact}. Recent tool calls: {transcript}")
        return f"Sorry, I can't finish this here. I've passed it to the school office (ref {ticket}) and they'll get back to you."
