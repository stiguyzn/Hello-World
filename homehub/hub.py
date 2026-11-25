"""Aggregates providers and caches their data for the web UI."""

from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List, Optional, Tuple

from .providers.base import Device, Event, Provider, ProviderError

log = logging.getLogger("homehub")


class Hub:
    def __init__(self, providers: List[Provider], cache_seconds: float = 15.0,
                 snapshot_seconds: float = 60.0):
        self.providers: Dict[str, Provider] = {p.name: p for p in providers}
        self.cache_seconds = cache_seconds
        self.errors: Dict[str, str] = {}
        self.snapshot_seconds = snapshot_seconds
        self._cache: Dict[str, Tuple[float, List[Device]]] = {}
        # Snapshots wake battery cameras, so several tablets or reloads share one.
        self._snaps: Dict[str, Tuple[float, bytes]] = {}
        self._lock = threading.Lock()

    def connect_all(self) -> None:
        """Connect each provider. A failing provider is reported, not fatal."""
        for name, p in list(self.providers.items()):
            try:
                p.connect()
                self.errors.pop(name, None)
            except Exception as e:  # keep the dashboard up even if one vendor fails
                log.warning("Provider %s failed to connect: %s", name, e)
                self.errors[name] = str(e)

    def _provider_devices(self, name: str, p: Provider, force: bool) -> List[Device]:
        with self._lock:
            hit = self._cache.get(name)
        if hit and not force and time.time() - hit[0] < self.cache_seconds:
            return hit[1]
        try:
            devs = p.devices()
            self.errors.pop(name, None)
        except Exception as e:
            log.warning("Provider %s devices failed: %s", name, e)
            self.errors[name] = str(e)
            return hit[1] if hit else []
        with self._lock:
            self._cache[name] = (time.time(), devs)
        return devs

    def devices(self, force: bool = False) -> List[Device]:
        out: List[Device] = []
        for name, p in self.providers.items():
            if name in self.errors and name not in self._cache and not force:
                continue  # never connected; don't hammer it every poll
            out.extend(self._provider_devices(name, p, force))
        return out

    def events(self, limit: int = 20) -> List[Event]:
        out: List[Event] = []
        for name, p in self.providers.items():
            try:
                out.extend(p.events(limit))
            except Exception as e:
                log.warning("Provider %s events failed: %s", name, e)
        out.sort(key=lambda e: e.at, reverse=True)
        return out[:limit]

    def _split(self, device_id: str) -> Tuple[Provider, str]:
        name, _, native = device_id.partition(":")
        p = self.providers.get(name)
        if p is None or not native:
            raise ProviderError(f"Unknown device {device_id}")
        return p, native

    def action(self, device_id: str, action: str) -> None:
        p, native = self._split(device_id)
        p.action(native, action)
        with self._lock:
            self._cache.pop(p.name, None)  # show the new state on the next poll
            if action == "snapshot":
                self._snaps.pop(device_id, None)

    def snapshot(self, device_id: str) -> Optional[bytes]:
        p, native = self._split(device_id)
        with self._lock:
            hit = self._snaps.get(device_id)
        if hit and time.time() - hit[0] < self.snapshot_seconds:
            return hit[1]
        img = p.snapshot(native)
        if img:
            with self._lock:
                self._snaps[device_id] = (time.time(), img)
        return img

    def status(self) -> dict:
        return {
            "providers": sorted(self.providers),
            "errors": dict(self.errors),
            "time": time.time(),
        }
