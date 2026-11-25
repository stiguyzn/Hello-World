"""Settings, read from environment variables with sensible defaults.

HOMEHUB_PROVIDERS   comma list of providers: demo, ring, blink  (default: demo)
HOMEHUB_HOST        address to listen on                          (default: 0.0.0.0)
HOMEHUB_PORT        port                                          (default: 8080)
HOMEHUB_DATA_DIR    where sign-in tokens are kept                 (default: ~/.homehub)
HOMEHUB_PIN         optional PIN the tablet must enter to arm/disarm
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Config:
    providers: List[str] = field(default_factory=lambda: ["demo"])
    host: str = "0.0.0.0"
    port: int = 8080
    data_dir: str = os.path.expanduser("~/.homehub")
    pin: Optional[str] = None

    @classmethod
    def from_env(cls, env=None) -> "Config":
        env = os.environ if env is None else env
        names = [p.strip().lower() for p in env.get("HOMEHUB_PROVIDERS", "demo").split(",") if p.strip()]
        return cls(
            providers=names or ["demo"],
            host=env.get("HOMEHUB_HOST", "0.0.0.0"),
            port=int(env.get("HOMEHUB_PORT", "8080")),
            data_dir=os.path.expanduser(env.get("HOMEHUB_DATA_DIR", "~/.homehub")),
            pin=env.get("HOMEHUB_PIN") or None,
        )

    @property
    def ring_token_file(self) -> str:
        return os.path.join(self.data_dir, "ring_token.json")

    @property
    def blink_cred_file(self) -> str:
        return os.path.join(self.data_dir, "blink_credentials.json")
