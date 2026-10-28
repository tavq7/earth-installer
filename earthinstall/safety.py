"""Sandbox safety invariants for the offline development phase.

Hard rules enforced here (acceptance non-goals of the project):
  1. No device access. This package imports no device tooling and offers no
     function that shells out. assert_no_device_tooling() fails loudly if any
     forbidden module got imported into the process, catching accidental use.
  2. All writes stay inside earth-installer/out/. guard_output_path() refuses
     anything else.
  3. Source artifacts (saved backups, original OTA packages) are read-only.
     open_source() opens 'rb' only and records a hash so callers can prove a
     file was not mutated; assert_untouched() re-checks it.

These are development-phase guards. They do not make a real install safe; they
make real device operations impossible from this code.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

# Package root is earth-installer/ (parent of the earthinstall/ dir).
PKG_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PKG_ROOT / "out"

# Modules whose mere presence in sys.modules means something is wired to talk to
# the device. We never import these. If a caller did, we refuse to run.
FORBIDDEN_MODULES = ("mtkclient", "usb", "usb1", "pyusb")

# Binary names the tool must never execute. Listed for documentation and for the
# audit test; this package shells out nowhere.
FORBIDDEN_BINARIES = ("adb", "fastboot", "mtk", "mtkclient", "fastbootd")


class SafetyViolation(RuntimeError):
    """Raised when a sandbox invariant would be broken."""


def assert_no_device_tooling() -> None:
    """Refuse to proceed if device-access modules were imported into the process."""
    present = [m for m in FORBIDDEN_MODULES if m in sys.modules]
    if present:
        raise SafetyViolation(
            "device-access module(s) loaded, refusing offline run: " + ", ".join(present)
        )


def guard_output_path(path: str | os.PathLike) -> Path:
    """Return a resolved path, or raise if it is not inside OUTPUT_DIR."""
    p = Path(path).resolve()
    out = OUTPUT_DIR.resolve()
    if p != out and out not in p.parents:
        raise SafetyViolation(f"write target outside out/ sandbox: {p}")
    return p


def ensure_output_dir() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def write_output(relpath: str, data: str, *, encoding: str = "utf-8") -> Path:
    """Write text strictly inside out/. Returns the path written."""
    ensure_output_dir()
    target = guard_output_path(OUTPUT_DIR / relpath)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(data, encoding=encoding)
    return target


def open_source(path: str | os.PathLike):
    """Open a source artifact strictly read-only (binary)."""
    return open(path, "rb")


def hash_file(path: str | os.PathLike, *, algo: str = "sha256", chunk: int = 1 << 20) -> str:
    h = hashlib.new(algo)
    with open_source(path) as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def assert_untouched(path: str | os.PathLike, expected_sha256: str) -> None:
    """Re-hash a source file and confirm it still matches (proves we didn't mutate it)."""
    actual = hash_file(path)
    if actual != expected_sha256:
        raise SafetyViolation(
            f"source artifact changed under us: {path}\n expected {expected_sha256}\n actual   {actual}"
        )
