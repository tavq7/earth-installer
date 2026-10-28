"""Device and partition compatibility validation (offline, from recorded evidence)."""

from __future__ import annotations

from .config import Profile


def check_device(profile: Profile, catalog: dict) -> dict:
    """Validate the install candidate is for this device and slot model."""
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str):
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    ic = catalog["install_candidate"]
    post_build = ic.get("post_build", "")
    codename = profile.device["codename"]
    add("codename-in-post-build",
        f"/{codename}:" in post_build or f"{codename}_" in post_build,
        f"post_build={post_build!r} must name device {codename!r}")

    add("ota-type-ab",
        ic.get("ota_type") == "AB" and profile.device["slotting"].startswith("A/B"),
        f"ota_type={ic.get('ota_type')} device_slotting={profile.device['slotting']}")

    add("block-size-match",
        int(ic.get("block_size", profile.block_size)) == profile.block_size,
        f"catalog block_size vs profile {profile.block_size}")

    sdk = ic.get("post_sdk_level")
    add("sdk-level-known", isinstance(sdk, int) and sdk > 0,
        f"post_sdk_level={sdk}")

    add("target-slot-is-inactive",
        profile.target_slot != profile.active_slot,
        f"install targets slot {profile.target_slot!r}; active slot is "
        f"{profile.active_slot!r} (must differ so the active OS stays bootable)")

    ok = all(c["pass"] for c in checks)
    return {"component": "device-compat", "pass": ok, "checks": checks}


def check_partitions(profile: Profile, catalog: dict) -> dict:
    """Validate each OTA payload partition maps to a known device partition."""
    phys = {p["name"]: p for p in profile.physical()}
    super_logicals = set(profile.partitions["super"]["logical_partitions"])
    super_name = profile.partitions["super"]["name"]
    protected = profile.protected_partition_names()

    rows: list[dict] = []
    problems: list[str] = []
    for part in catalog["ota_payload_partitions"]:
        name = part["name"]
        included = part.get("included", True)
        # Map OTA names to device partitions. preloader_raw -> preloader.
        phys_name = "preloader" if name == "preloader_raw" else name
        if phys_name in phys:
            target, kind = phys_name, "physical"
        elif name in super_logicals:
            target, kind = super_name, "dynamic-in-super"
        else:
            target, kind = None, "unmapped"
            problems.append(f"OTA partition {name!r} maps to no known device partition")

        is_protected = phys_name in protected
        row = {"ota_partition": name, "maps_to": target, "kind": kind,
               "included_in_install": included, "protected": is_protected}

        # Invariant: a protected partition must NOT be in the install set.
        if is_protected and included:
            problems.append(
                f"protected partition {phys_name!r} is marked included — would "
                f"overwrite preserved {phys_name} (unlock/brick risk)")
            row["violation"] = "protected-but-included"
        rows.append(row)

    # Every dynamic logical the profile expects should appear in the payload.
    payload_names = {p["name"] for p in catalog["ota_payload_partitions"]}
    for logical in super_logicals:
        if logical not in payload_names:
            problems.append(f"expected dynamic partition {logical!r} absent from OTA payload")

    ok = not problems
    return {"component": "partition-compat", "pass": ok,
            "rows": rows, "problems": problems,
            "super_group_for_target_slot": f"main_{profile.target_slot}"}
