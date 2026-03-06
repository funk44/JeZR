import os
import sys
from abc import ABC, abstractmethod


class Notifier(ABC):
    @abstractmethod
    def send(self, message: str) -> None:
        """Send a message to the athlete."""
        ...


class StdoutNotifier(Notifier):
    """Prints messages to stdout. Default for standalone/CLI use."""

    def send(self, message: str) -> None:
        print(message)


class OpenClawNotifier(Notifier):
    """Delivers messages via OpenClaw's outbox file.

    OpenClaw monitors a designated outbox file and forwards new lines to WhatsApp.
    The outbox path is read from JEZR_OPENCLAW_OUTBOX env var.
    Each message is written as a single line (newlines within message replaced with
    the literal two-character sequence \\n).
    If the outbox path is not set, falls back to StdoutNotifier with a warning.
    """

    def __init__(self) -> None:
        self._outbox = os.getenv("JEZR_OPENCLAW_OUTBOX", "")
        if not self._outbox:
            print(
                "WARNING: JEZR_OPENCLAW_OUTBOX not set — OpenClawNotifier falling back to stdout.",
                file=sys.stderr,
            )
        self._fallback = StdoutNotifier()

    def send(self, message: str) -> None:
        if not self._outbox:
            self._fallback.send(message)
            return
        line = message.replace("\n", "\\n")
        with open(self._outbox, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def get_notifier() -> Notifier:
    """Return the configured notifier based on JEZR_NOTIFIER env var.

    Values: 'openclaw' | 'stdout' (default: 'stdout')
    """
    kind = os.getenv("JEZR_NOTIFIER", "stdout").strip().lower()
    if kind == "openclaw":
        return OpenClawNotifier()
    return StdoutNotifier()
