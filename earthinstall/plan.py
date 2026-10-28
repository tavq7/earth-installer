"""Dry-run A/B + dynamic-partition install plan. Produces a plan only; executes nothing."""

from __future__ import annotations

from .config import Profile


def build_plan(profile: Profile, catalog: dict) -> dict:
    target = profile.target_slot
    protected = profile.protected_partition_names()
    super_name = profile.partitions["super"]["name"]
    super_logicals = set(profile.partitions["super"]["logical_partitions"])
    block = profile.block_size

    phys_writes: list[dict] = []
    dynamic_writes: list[dict] = []
    skipped: list[dict] = []

    for part in catalog["ota_payload_partitions"]:
        name = part["name"]
        phys_name = "preloader" if name == "preloader_raw" else name
        if not part.get("included", True) or phys_name in protected:
            skipped.append({"partition": name,
                            "reason": "excluded from install (protected / not in OTA set)"})
            continue
        op = {"ota_partition": name, "size": part["size"],
              "sha256": part["sha256"], "block_size": block,
              "size_block_aligned": part["size"] % block == 0}
        if name in super_logicals:
            op["target"] = f"{super_name} (logical in group main_{target})"
            dynamic_writes.append(op)
        else:
            op["target"] = f"{phys_name}_{target}"
            phys_writes.append(op)

    # Device operations are described, never performed, and flagged device_op.
    device_ops = [
        {"op": "flash-physical", "mode": "bootloader-fastboot",
         "count": len(phys_writes), "device_op": True,
         "note": "write each listed physical image to its _%s slot" % target},
        {"op": "flash-super", "mode": "bootloader-fastboot",
         "count": len(dynamic_writes), "device_op": True,
         "note": "write the rebuilt super (group main_%s); bootloader-mode is "
                 "LK-gated and permitted, fastbootd is not (locked seccfg)" % target},
        {"op": "set-active", "slot": target, "device_op": True,
         "note": "restores slot %s retry counter; required for first boot" % target},
    ]

    return {
        "component": "install-plan",
        "mode": "DRY-RUN (no device access in this phase)",
        "target_slot": target,
        "active_slot_preserved": profile.active_slot,
        "physical_writes": phys_writes,
        "dynamic_writes": dynamic_writes,
        "skipped": skipped,
        "device_ops_planned": device_ops,
        "invariants": [
            "writes target ONLY slot %r; active slot %r is never written"
            % (target, profile.active_slot),
            "protected partitions never written: %s" % sorted(protected),
            "all image sizes block-aligned to %d" % block,
        ],
        "pass": all(w["size_block_aligned"] for w in phys_writes + dynamic_writes),
    }
