"""Recovery and rollback planning (offline). Produces a plan; executes nothing."""

from __future__ import annotations

from .config import Profile


def build_rollback(profile: Profile, catalog: dict) -> dict:
    rb = catalog.get("rollback_images", {})
    target = profile.target_slot
    # Safety net is the resolved running slot (left untouched by the install),
    # NOT the fixture active_slot.
    active = profile.resolve_running_slot()["slot"]

    # Primary recovery: the running slot was never touched, so the first recovery
    # is simply to keep booting it and set-active back to it if it was changed.
    recovery_tiers = [
        {"tier": 0, "name": "no-op / abort",
         "trigger": "install not yet set-active, or new slot fails first boot",
         "action": f"keep booting untouched active slot {active!r}; set-active "
                   f"back to {active!r} if it was changed",
         "device_op": True,
         "data_loss": False},
        {"tier": 1, "name": "return-to-stock (OS/AVB layer only)",
         "trigger": "slot b unbootable and active slot also compromised",
         "action": "flash verified stock boot/dtbo/vbmeta*/super from the "
                   "rollback ROM; DO NOT flash lk/preloader (preserve unlock)",
         "images": [e["name"] for e in rb.get("entries", [])],
         "device_op": True,
         "data_loss": True},
        {"tier": 2, "name": "restore preserved firmware",
         "trigger": "lk/preloader state corrupted despite protection",
         "action": "restore from preservation backups via BROM/DA (read-verified "
                   "copies: lk_a, lk_b, preloader_boot1, seccfg)",
         "images": [e["role"] for e in profile.protected_backups["entries"]],
         "device_op": True,
         "data_loss": True,
         "note": "BROM net is the last-resort recovery path; requires physical BROM entry"},
    ]

    # Each written partition is mapped to how it would be rolled back.
    coverage: list[dict] = []
    rb_names = {e["name"] for e in rb.get("entries", [])}
    super_logicals = set(profile.partitions["super"]["logical_partitions"])
    for part in catalog["ota_payload_partitions"]:
        name = part["name"]
        phys = "preloader" if name == "preloader_raw" else name
        if phys in profile.protected_partition_names() or not part.get("included", True):
            continue
        if name in super_logicals:
            covered = "super" in rb_names
            src = "rollback super.img (sparse)"
        elif phys in rb_names:
            covered = True
            src = f"rollback {phys}.img"
        else:
            covered = False
            src = "NO stock rollback image on hand"
        coverage.append({"written_partition": name, "rollback_source": src,
                         "covered": covered})

    uncovered = [c["written_partition"] for c in coverage if not c["covered"]]
    return {
        "component": "rollback-plan",
        # Incomplete rollback coverage is a blocking condition, not success.
        "pass": not uncovered,
        "coverage_complete": not uncovered,
        "unresolved": bool(uncovered),
        "active_slot_is_safety_net": active,
        "target_slot": target,
        "recovery_tiers": recovery_tiers,
        "partition_rollback_coverage": coverage,
        "uncovered_partitions": uncovered,
        "note": "Tier 0 (untouched active slot) is the real first-line safety net; "
                "it is why installing to the inactive slot is required.",
    }
