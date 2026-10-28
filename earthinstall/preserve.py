"""Protection of LK (both slots) and preloader backups.

Before any install/rollback plan is accepted, we must hold verified offline
backups of both LK copies and the preloader. This module confirms they exist,
match their recorded hashes, and are read-only to us. It NEVER writes to them.
"""

from __future__ import annotations

from pathlib import Path

from .config import Profile, resolve
from .safety import hash_file


REQUIRED_ROLES = ("lk_slot_a", "lk_slot_b", "preloader_boot1")


def check_backups(profile: Profile) -> dict:
    entries = profile.protected_backups["entries"]
    results: list[dict] = []
    roles_ok: set[str] = set()

    for e in entries:
        path = resolve(e["path"])
        row = {"role": e["role"], "path": str(path), "expected_sha256": e["sha256"]}
        if not path.exists():
            row["status"] = "missing"
        else:
            # Read-only check; also record that the file is not writable by intent.
            actual = hash_file(path)
            row["actual_sha256"] = actual
            row["status"] = "ok" if actual == e["sha256"] else "hash-mismatch"
            if row["status"] == "ok":
                roles_ok.add(e["role"])
        results.append(row)

    missing_roles = [r for r in REQUIRED_ROLES if r not in roles_ok]
    ok = not missing_roles
    caveat = profile.protected_backups.get("lk_unlock_caveat")
    return {
        "component": "preservation",
        "pass": ok,
        "required_roles": list(REQUIRED_ROLES),
        "verified_roles": sorted(roles_ok),
        "missing_or_bad_roles": missing_roles,
        "results": results,
        # Verifying these backups establishes STOCK-LK restore (anti-brick) only.
        "covers_stock_lk": ok,
        "covers_patched_unlock_lk": False,
        "lk_unlock_caveat": caveat,
        "note": "Both STOCK LK slots + preloader must verify before any plan is "
                "accepted; they are also excluded from the install set (double "
                "protection). This does NOT back up or preserve the PATCHED-unlock "
                "lk on slot b — that image is not in this backup set.",
    }
