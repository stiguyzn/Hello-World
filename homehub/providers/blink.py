"""Blink provider (Blink Outdoor/Indoor/Mini cameras and sync modules).

Uses the unofficial ``blinkpy`` library (``pip install blinkpy``).

GUESS: written against blinkpy 0.23.x, which is async and takes an aiohttp
session. Names used here (Blink.start, Auth(no_prompt=True), send_2fa_code,
blink.save, camera.async_arm, sync.async_arm, camera.snap_picture,
camera.image_from_cache) match that release; check them if you install a
different version.

Sign-in: run ``python -m homehub.main --setup blink`` once to enter your
email, password and the PIN Blink emails or texts you. That saves a
credentials file to the data folder.
"""

from __future__ import annotations

import os
from typing import List, Optional

from . import _async
from .base import Device, Event, Provider, ProviderError, now


class BlinkProvider(Provider):
    name = "blink"

    def __init__(self, cred_file: str):
        self.cred_file = cred_file
        self._blink = None
        self._session = None

    def connect(self) -> None:
        try:
            from aiohttp import ClientSession  # type: ignore
            from blinkpy.auth import Auth  # type: ignore
            from blinkpy.blinkpy import Blink  # type: ignore
            from blinkpy.helpers.util import json_load  # type: ignore
        except ImportError as e:
            raise ProviderError("blinkpy is not installed (pip install blinkpy)") from e
        if not os.path.exists(self.cred_file):
            raise ProviderError("No Blink sign-in yet. Run: python -m homehub.main --setup blink")

        async def _connect():
            self._session = ClientSession()
            blink = Blink(session=self._session)
            blink.auth = Auth(await json_load(self.cred_file), no_prompt=True, session=self._session)
            await blink.start()
            await blink.save(self.cred_file)  # keep refreshed tokens
            return blink

        self._blink = _async.run(_connect(), timeout=60)

    def setup_interactive(self) -> None:  # pragma: no cover - needs a real account
        from getpass import getpass

        from aiohttp import ClientSession  # type: ignore
        from blinkpy.auth import Auth  # type: ignore
        from blinkpy.blinkpy import Blink  # type: ignore

        email = input("Blink email: ")
        password = getpass("Blink password: ")

        async def _login():
            async with ClientSession() as session:
                blink = Blink(session=session)
                blink.auth = Auth({"username": email, "password": password},
                                  no_prompt=True, session=session)
                await blink.start()
                if blink.key_required:
                    await blink.send_2fa_code(input("PIN from Blink: "))
                os.makedirs(os.path.dirname(self.cred_file) or ".", exist_ok=True)
                await blink.save(self.cred_file)

        _async.run(_login(), timeout=180)
        try:
            os.chmod(self.cred_file, 0o600)
        except OSError:
            pass
        print(f"Saved Blink sign-in to {self.cred_file}")

    def _require(self):
        if self._blink is None:
            raise ProviderError("Blink is not connected")
        return self._blink

    def devices(self) -> List[Device]:
        blink = self._require()
        _async.run(blink.refresh(force=True), timeout=60)
        out: List[Device] = []
        for name, sync in blink.sync.items():
            out.append(Device(
                id=self.make_id(f"sync:{name}"),
                name=f"{name} (Blink system)",
                kind="alarm",
                provider=self.name,
                online=bool(getattr(sync, "online", True)),
                armed=bool(sync.arm),
                actions=["arm", "disarm"],
                extra={"native_id": f"sync:{name}"},
            ))
        for name, cam in blink.cameras.items():
            # Blink reports battery as "ok"/"low", not a percentage.
            batt = getattr(cam, "battery", None)
            out.append(Device(
                id=self.make_id(f"cam:{name}"),
                name=name,
                kind="camera",
                provider=self.name,
                armed=bool(getattr(cam, "arm", False)),
                motion_enabled=bool(getattr(cam, "motion_enabled", False)),
                battery=None,
                has_snapshot=True,
                actions=["snapshot", "arm", "disarm"],
                extra={"native_id": f"cam:{name}", "battery_state": batt,
                       "temperature": getattr(cam, "temperature", None)},
            ))
        return out

    def events(self, limit: int = 20) -> List[Event]:
        # blinkpy exposes only the latest motion flag per camera, not a history,
        # so this reports "motion now" rather than a timeline.
        blink = self._require()
        out = []
        for name, cam in blink.cameras.items():
            if getattr(cam, "motion_detected", False):
                out.append(Event(self.make_id(f"cam:{name}"), name, "motion",
                                 now(), self.name))
        return out[:limit]

    def action(self, native_id: str, action: str) -> None:
        blink = self._require()
        kind, _, name = native_id.partition(":")
        if action in ("arm", "disarm"):
            target = blink.sync.get(name) if kind == "sync" else blink.cameras.get(name)
            if target is None:
                raise ProviderError(f"Unknown Blink device {name}")
            _async.run(target.async_arm(action == "arm"))
        elif action == "snapshot" and kind == "cam":
            cam = blink.cameras.get(name)
            if cam is None:
                raise ProviderError(f"Unknown Blink camera {name}")
            _async.run(cam.snap_picture(), timeout=60)
        else:
            raise ProviderError(f"Blink does not support '{action}'")

    def snapshot(self, native_id: str) -> Optional[bytes]:
        blink = self._require()
        kind, _, name = native_id.partition(":")
        cam = blink.cameras.get(name) if kind == "cam" else None
        if cam is None:
            return None
        return getattr(cam, "image_from_cache", None)
