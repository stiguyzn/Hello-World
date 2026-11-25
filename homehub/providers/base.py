"""Common provider interface and device model.

Every provider (Ring, Blink, demo) turns its own SDK objects into plain
``Device`` and ``Event`` records so the web UI never needs to know which
vendor a camera came from.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional


# Device kinds the UI knows how to draw.
KINDS = ("camera", "doorbell", "light", "alarm", "sensor")


@dataclass
class Device:
    id: str                      # globally unique: "<provider>:<native id>"
    name: str
    kind: str                    # one of KINDS
    provider: str
    online: bool = True
    battery: Optional[int] = None        # percent, None when mains powered
    armed: Optional[bool] = None         # cameras / alarm systems
    on: Optional[bool] = None            # lights
    motion_enabled: Optional[bool] = None
    last_motion: Optional[float] = None  # unix seconds
    has_snapshot: bool = False
    actions: List[str] = field(default_factory=list)
    extra: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Event:
    device_id: str
    device_name: str
    kind: str          # "motion", "ding", "arm", "disarm", ...
    at: float          # unix seconds
    provider: str
    detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class ProviderError(Exception):
    """Raised for failures the UI should show to the person."""


class Provider:
    """Base class. Subclasses override the methods they support."""

    name = "base"

    def connect(self) -> None:
        """Sign in / open sessions. Called once at start-up."""

    def devices(self) -> List[Device]:
        raise NotImplementedError

    def events(self, limit: int = 20) -> List[Event]:
        return []

    def action(self, native_id: str, action: str) -> None:
        raise ProviderError(f"{self.name} does not support '{action}'")

    def snapshot(self, native_id: str) -> Optional[bytes]:
        """Return a JPEG for the camera, or None if there isn't one."""
        return None

    # Helpers -------------------------------------------------------------
    def make_id(self, native_id: object) -> str:
        return f"{self.name}:{native_id}"


def now() -> float:
    return time.time()
