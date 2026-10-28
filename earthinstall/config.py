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
