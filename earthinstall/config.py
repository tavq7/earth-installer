"""Load the reproducible device profile and image catalog."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .safety import PKG_ROOT

CONFIG_DIR = PKG_ROOT / "config"
DEVICE_PROFILE = CONFIG_DIR / "device-profile.json"
KNOWN_IMAGES = CONFIG_DIR / "known-images.json"


def _load(path: Path) -> dict:
    with open(path, "rb") as f:
        return json.load(f)


@dataclass
class Profile:
    device: dict
    observed_state: dict
    install_target: dict
    partitions: dict
    protected_backups: dict

    @property
    def block_size(self) -> int:
        return int(self.partitions["block_size"])

    @property
    def slots(self) -> list[str]:
        return list(self.device["slots"])

    @property
    def target_slot(self) -> str:
        return self.install_target["slot"]

    @property
    def active_slot(self) -> str:
        return self.observed_state["active_slot"]

    @property
    def active_slot_is_fixture(self) -> bool:
        return bool(self.observed_state.get("active_slot_is_fixture"))

    def resolve_running_slot(self, fresh_active_slot: str | None = None,
                             fresh_source: str | None = None) -> dict:
        """Decide which slot is the running/active one, and how trustworthy that is.

        Priority: explicit fresh evidence > last_confirmed_running record > fixture.
        Returns {slot, source, is_fresh, is_fixture}. Fixture is never treated as
        fresh device evidence.
        """
        if fresh_active_slot:
            return {"slot": fresh_active_slot,
                    "source": fresh_source or "caller-supplied fresh slot evidence",
                    "is_fresh": True, "is_fixture": False}
        lcr = self.observed_state.get("last_confirmed_running")
        if lcr and lcr.get("slot"):
            return {"slot": lcr["slot"], "source": lcr.get("source", "last_confirmed_running"),
                    "is_fresh": False, "is_fixture": bool(lcr.get("is_fixture"))}
        return {"slot": self.active_slot, "source": "fixture (active_slot)",
                "is_fresh": False, "is_fixture": self.active_slot_is_fixture}

    @property
    def super_shared(self) -> bool:
        return bool(self.partitions["super"].get("physical_super_shared"))

    @property
    def super_preserves_other_slot(self) -> str:
        return self.partitions["super"].get("raw_rewrite_preserves_other_slot", "unproven")

    def physical(self) -> list[dict]:
        return list(self.partitions["physical"])

    def protected_partition_names(self) -> set[str]:
        return {p["name"] for p in self.physical() if p.get("protected")}

    def ota_written_partition_names(self) -> set[str]:
        names = {p["name"] for p in self.physical() if p.get("ota_written")}
        if self.partitions["super"].get("ota_written"):
            names.add(self.partitions["super"]["name"])
        return names


def load_profile(path: Path | None = None) -> Profile:
    data = _load(path or DEVICE_PROFILE)
    return Profile(
        device=data["device"],
        observed_state=data["observed_state"],
        install_target=data["install_target"],
        partitions=data["partitions"],
        protected_backups=data["protected_backups"],
    )


def load_catalog(path: Path | None = None) -> dict:
    return _load(path or KNOWN_IMAGES)


def resolve(path_from_config: str, base: Path | None = None) -> Path:
    """Config paths are written relative to config/. Resolve them against it."""
    base = base or CONFIG_DIR
    return (base / path_from_config).resolve()
