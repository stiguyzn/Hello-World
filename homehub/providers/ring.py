"""Ring provider (doorbells, Stick Up Cams, floodlight/spotlight cams).

Uses the unofficial ``ring_doorbell`` library (``pip install ring_doorbell``).
Ring has no public API, so this can break when Ring changes things.

GUESS: written against ring_doorbell 0.9.x, which is fully async. Method
names below (async_update_data, async_history, async_get_snapshot,
async_set_lights, async_set_motion_detection) match that release; check
them if you install a different version.

Sign-in: run ``python -m homehub.main --setup ring`` once on a computer to
enter your email, password and 2FA code. That saves a refresh token to the
data folder, and the hub uses only the token after that.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

from . import _async
from .base import Device, Event, Provider, ProviderError

USER_AGENT = "HomeHub/0.1"


class RingProvider(Provider):
    name = "ring"

    def __init__(self, token_file: str):
        self.token_file = token_file
        self._ring = None
        self._by_id: Dict[str, object] = {}

    # -- auth -------------------------------------------------------------
    def _save_token(self, token: dict) -> None:
        os.makedirs(os.path.dirname(self.token_file) or ".", exist_ok=True)
        with open(self.token_file, "w") as f:
            json.dump(token, f)
        try:
            os.chmod(self.token_file, 0o600)
        except OSError:
            pass

    def connect(self) -> None:
        try:
            from ring_doorbell import Auth, Ring  # type: ignore
        except ImportError as e:
            raise ProviderError("ring_doorbell is not installed (pip install ring_doorbell)") from e
        if not os.path.exists(self.token_file):
            raise ProviderError("No Ring token yet. Run: python -m homehub.main --setup ring")
        with open(self.token_file) as f:
            token = json.load(f)

        async def _connect():
            auth = Auth(USER_AGENT, token, self._save_token)
            ring = Ring(auth)
            await ring.async_update_data()
            return ring

        self._ring = _async.run(_connect())

    def setup_interactive(self) -> None:  # pragma: no cover - needs a real account
        from getpass import getpass

        from ring_doorbell import Auth, Requires2FAError  # type: ignore

        email = input("Ring email: ")
        password = getpass("Ring password: ")

        async def _login():
            auth = Auth(USER_AGENT, None, self._save_token)
            try:
                await auth.async_fetch_token(email, password)
            except Requires2FAError:
                await auth.async_fetch_token(email, password, input("2FA code: "))

        _async.run(_login(), timeout=120)
        print(f"Saved Ring token to {self.token_file}")

    # -- data -------------------------------------------------------------
    def _all(self):
        if self._ring is None:
            raise ProviderError("Ring is not connected")
        _async.run(self._ring.async_update_devices())
        devs = self._ring.devices()
        out = []
        for kind, group in (("doorbell", devs.doorbots + devs.authorized_doorbots),
                            ("camera", devs.stickup_cams)):
            for d in group:
                out.append((kind, d))
        return out

    def devices(self) -> List[Device]:
        result = []
        self._by_id = {}
        for kind, d in self._all():
            native = str(d.id)
            self._by_id[native] = d
            actions = ["snapshot", "motion_on", "motion_off"]
            has_light = _safe(lambda: d.has_capability("light"), False)
            if has_light:
                actions += ["light_on", "light_off"]
            battery = _safe(lambda: d.battery_life, None)
            result.append(Device(
                id=self.make_id(native),
                name=d.name,
                kind=kind,
                provider=self.name,
                online=_safe(lambda: d.connection_status != "offline", True),
                battery=int(battery) if isinstance(battery, (int, float)) else None,
                motion_enabled=_safe(lambda: d.motion_detection, None),
                on=(_safe(lambda: d.lights == "on", None) if has_light else None),
                has_snapshot=True,
                actions=actions,
                extra={"native_id": native, "model": _safe(lambda: d.model, "")},
            ))
        return result

    def events(self, limit: int = 20) -> List[Event]:
        out: List[Event] = []
        for _, d in self._all():
            hist = _safe(lambda: _async.run(d.async_history(limit=5)), []) or []
            for h in hist:
                at = h.get("created_at")
                if isinstance(at, str):
                    at = datetime.fromisoformat(at.replace("Z", "+00:00"))
                ts = at.timestamp() if isinstance(at, datetime) else 0.0
                out.append(Event(self.make_id(d.id), d.name, h.get("kind", "event"), ts, self.name))
        out.sort(key=lambda e: e.at, reverse=True)
        return out[:limit]

    def _get(self, native_id: str):
        d = self._by_id.get(native_id)
        if d is None:
            self.devices()
            d = self._by_id.get(native_id)
        if d is None:
            raise ProviderError(f"Unknown Ring device {native_id}")
        return d

    def action(self, native_id: str, action: str) -> None:
        d = self._get(native_id)
        if action == "light_on":
            _async.run(d.async_set_lights("on"))
        elif action == "light_off":
            _async.run(d.async_set_lights("off"))
        elif action in ("motion_on", "motion_off"):
            _async.run(d.async_set_motion_detection(action == "motion_on"))
        elif action == "snapshot":
            pass  # the UI fetches /api/snapshot afterwards
        else:
            raise ProviderError(f"Ring does not support '{action}'")

    def snapshot(self, native_id: str) -> Optional[bytes]:
        d = self._get(native_id)
        # Ring snapshots wake battery cameras, so this is slow and drains them.
        return _async.run(d.async_get_snapshot(), timeout=45)


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default
