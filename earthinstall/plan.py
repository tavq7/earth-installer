"""Dry-run A/B + dynamic-partition install plan. Produces a plan only; executes nothing.

A plan is always structurally produced for inspection, but it is NOT marked
device-ready unless fresh, explicitly-identified slot evidence proves the target
slot is not the running slot. Fixture data can never make a plan device-ready.
"""

from __future__ import annotations

from .config import Profile


def build_plan(profile: Profile, catalog: dict,
               fresh_active_slot: str | None = None,
               fresh_source: str | None = None) -> dict:
    target = profile.target_slot
    protected = profile.protected_partition_names()
    super_name = profile.partitions["super"]["name"]
    super_logicals = set(profile.partitions["super"]["logical_partitions"])
    block = profile.block_size

    running = profile.resolve_running_slot(fresh_active_slot, fresh_source)

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

    # Device-readiness gate (independent of structural validity).
    blockers: list[str] = []
    if running["is_fixture"]:
        blockers.append(
            "running-slot evidence is a FIXTURE, not a live reading; refuse to "
            "declare device-ready. Supply fresh_active_slot with a source.")
    if not running["is_fresh"]:
        blockers.append(
            "no fresh live slot evidence at plan time (using %r from %s); "
            "re-read slot/unlock state on-device before any write"
            % (running["slot"], running["source"]))
    if target == running["slot"]:
        blockers.append(
            "target slot %r == running slot %r (source: %s). Refusing: an install "
            "must target the INACTIVE slot so the running system stays bootable."
            % (target, running["slot"], running["source"]))

    # Shared-super preservation is a separate real-world blocker.
    if profile.super_shared and dynamic_writes and \
            profile.super_preserves_other_slot != "proven":
        blockers.append(
            "raw-super rewrite preservation of the other slot's logical group is "
            "%r; super is one shared physical partition (see block-device-simulation)"
            % profile.super_preserves_other_slot)

    device_ready = not blockers

    device_ops = [
        {"op": "flash-physical", "mode": "bootloader-fastboot",
         "count": len(phys_writes), "device_op": True,
         "note": "write each listed physical image to its _%s slot" % target},
        {"op": "flash-super", "mode": "bootloader-fastboot",
         "count": len(dynamic_writes), "device_op": True,
         "note": "write the rebuilt super (group main_%s)" % target},
        {"op": "set-active", "slot": target, "device_op": True,
         "note": "restores slot %s retry counter; required for first boot" % target},
    ]

    return {
        "component": "install-plan",
        "mode": "DRY-RUN (no device access in this phase)",
        "target_slot": target,
        "running_slot": running,
        "device_ready": device_ready,
        "device_ready_blockers": blockers,
        "physical_writes": phys_writes,
        "dynamic_writes": dynamic_writes,
        "skipped": skipped,
        "device_ops_planned": device_ops,
        "invariants": [
            "writes target ONLY slot %r; running slot %r must never be written"
            % (target, running["slot"]),
            "protected partitions never written: %s" % sorted(protected),
            "all image sizes block-aligned to %d" % block,
        ],
        # Structural validity of the plan (alignment). Device-readiness is the
        # separate device_ready flag above and must not be conflated with this.
        "structurally_valid": all(w["size_block_aligned"]
                                  for w in phys_writes + dynamic_writes),
        "pass": all(w["size_block_aligned"] for w in phys_writes + dynamic_writes),
    }
