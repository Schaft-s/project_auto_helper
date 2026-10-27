from __future__ import annotations

from dataclasses import dataclass, field

from autonaparnik.domain.models import HistoryMessage


@dataclass
class ChatSession:
    audience: str = "owner"
    history: list[HistoryMessage] = field(default_factory=list)

    def remember_user(self, text: str) -> None:
        self.history.append(HistoryMessage(role="user", text=text[:6000]))
        self.history = self.history[-12:]

    def remember_assistant(self, text: str) -> None:
        cleaned = " ".join(text.split())[:400]
        if not cleaned:
            return
        self.history.append(HistoryMessage(role="assistant", text=cleaned))
        self.history = self.history[-12:]
