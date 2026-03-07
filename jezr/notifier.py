import os
import subprocess
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
    """Send messages via the OpenClaw CLI (openclaw message send)."""

    def __init__(self, target: str, channel: str = "whatsapp") -> None:
        """
        Args:
            target: Phone number or handle to send to (e.g. +61430220917)
            channel: OpenClaw channel (default: whatsapp)
        """
        self.target = target
        self.channel = channel

    def send(self, message: str) -> None:
        cmd = [
            "openclaw", "message", "send",
            "--channel", self.channel,
            "--target", self.target,
            "--message", message,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"OpenClaw send failed (exit {result.returncode}): {result.stderr.strip()}"
            )


def get_notifier() -> Notifier:
    """Return the configured notifier based on JEZR_NOTIFIER env var.

    Values: 'openclaw' | 'stdout' (default: 'stdout')
    """
    notifier_type = os.environ.get("JEZR_NOTIFIER", "stdout").lower()

    if notifier_type == "openclaw":
        target = os.environ.get("JEZR_OPENCLAW_TARGET")
        channel = os.environ.get("JEZR_OPENCLAW_CHANNEL", "whatsapp")

        if not target:
            print(
                "WARNING: JEZR_OPENCLAW_TARGET not set — OpenClawNotifier falling back to stdout.",
                file=sys.stderr,
            )
            return StdoutNotifier()

        return OpenClawNotifier(target=target, channel=channel)

    return StdoutNotifier()
