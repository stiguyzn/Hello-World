"""Demo provider: fake devices so the dashboard works with no accounts.

Useful for trying the layout on the tablet before signing in to Ring or
Blink, and it is what the tests run against.
"""

from __future__ import annotations

import random
import threading
from typing import Dict, List, Optional

from .base import Device, Event, Provider, ProviderError, now

# A tiny grey 1x1 JPEG, so the snapshot endpoint returns a real image.
_PLACEHOLDER_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909"
    "080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30"
    "313434341f27393d38323c2e333432ffc0000b080001000101011100ffc4001f0000010501"
    "010101010100000000000000000102030405060708090a0bffc400b5100002010303020403"
    "050504040000017d01020300041105122131410613516107227114328191a1082342b1c115"
    "52d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a53"
    "5455565758595a636465666768696a737475767778797a838485868788898a929394959697"
    "98999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8"
    "d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00fbd3ffd9"
)


class DemoProvider(Provider):
    name = "demo"

    def __init__(self, seed: Optional[int] = None):
        self._lock = threading.Lock()
        self._rand = random.Random(seed)
        t = now()
        self._devices: Dict[str, Device] = {}
        for d in [
            Device(id="", name="Front Door", kind="doorbell", provider=self.name,
                   battery=82, motion_enabled=True, last_motion=t - 300,
                   has_snapshot=True,
                   actions=["snapshot", "motion_on", "motion_off"]),
            Device(id="", name="Driveway", kind="camera", provider=self.name,
                   battery=64, armed=True, motion_enabled=True,
                   last_motion=t - 3600, has_snapshot=True,
                   actions=["snapshot", "arm", "disarm"]),
            Device(id="", name="Back Garden", kind="camera", provider=self.name,
                   battery=23, armed=False, motion_enabled=True,
                   has_snapshot=True, actions=["snapshot", "arm", "disarm"]),
            Device(id="", name="Porch Light", kind="light", provider=self.name,
                   on=False, actions=["light_on", "light_off"]),
            Device(id="", name="Home System", kind="alarm", provider=self.name,
                   armed=False, actions=["arm", "disarm"]),
        ]:
            native = d.name.lower().replace(" ", "_")
            d.id = self.make_id(native)
            d.extra["native_id"] = native
            self._devices[native] = d
        self._events: List[Event] = [
            Event(self._devices["front_door"].id, "Front Door", "ding", t - 900, self.name),
            Event(self._devices["front_door"].id, "Front Door", "motion", t - 300, self.name),
            Event(self._devices["driveway"].id, "Driveway", "motion", t - 3600, self.name),
        ]

    def devices(self) -> List[Device]:
        with self._lock:
            return list(self._devices.values())

    def events(self, limit: int = 20) -> List[Event]:
        with self._lock:
            return sorted(self._events, key=lambda e: e.at, reverse=True)[:limit]

    def action(self, native_id: str, action: str) -> None:
        with self._lock:
            dev = self._devices.get(native_id)
            if dev is None:
                raise ProviderError(f"Unknown device {native_id}")
            if action not in dev.actions:
                raise ProviderError(f"{dev.name} does not support '{action}'")
            if action in ("arm", "disarm"):
                dev.armed = action == "arm"
            elif action in ("light_on", "light_off"):
                dev.on = action == "light_on"
            elif action in ("motion_on", "motion_off"):
                dev.motion_enabled = action == "motion_on"
            elif action == "snapshot":
                pass
            self._events.append(Event(dev.id, dev.name, action, now(), self.name))

    def snapshot(self, native_id: str) -> Optional[bytes]:
        dev = self._devices.get(native_id)
        if dev is None or not dev.has_snapshot:
            return None
        return _PLACEHOLDER_JPEG
