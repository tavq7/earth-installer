# What remains before real-world validation

The offline tool validates its own planning model (Tier 1). It does **not** and
**cannot** assert installation readiness: the `all` command never exits with a
ready verdict, and the report marks real-world readiness **NOT ESTABLISHED**.
Everything below is open and cannot be closed offline. Nothing here is clearance
to flash.

**Observed vs target.** LineageOS **23.2 booted on slot B** (operator-confirmed).
The **24.0 upgrade is unvalidated** — not installed, not booted. The profile's
`active_slot=a` is a **fixture only** and is never used as running-slot evidence.

## 1. Cryptographic trust is not established
The tool checks that images match recorded SHA-256 values. It does **not** verify
the LineageOS signing chain, the OTA `payload.bin` signature, or AVB/vbmeta
descriptors against a trusted key. `custom-build/verification.json` already
records this as the open gate ("CUSTOM OTA BLOCKED ON ACCEPTED SIGNING PATH").
Hash equality only proves the bytes are the ones we previously saw.

## 2. Fresh slot evidence is required; target must not equal the running slot
The 24.0 plan targets slot `b`, but slot `b` is the last confirmed running slot
(23.2). Targeting the running slot is refused. A real plan needs the current slot
**freshly re-read on-device** (`--fresh-active-slot` with a source), and the
target must be the inactive slot. Until then `device_ready=False`. Fixture data
(`active_slot=a`) is never accepted as evidence.

## 2a. AVB orange-state boot of the 24.0 upgrade
Even with the slot resolved, it is unproven that a LineageOS 24.0 slot image
passes verified-boot under the LK-only unlock and boots. On-device test only; the
simulator models block writes/interruption, not AVB, dm-verity, or boot-control.

## 2b. `super` is one shared physical partition — preservation unproven
`super` is a single physical partition; `main_a`/`main_b` are logical groups
inside it. A raw-super rewrite replaces the whole partition, so it overwrites the
other slot's logical data unless the rebuilt image provably carries that slot's
group. Earlier work rebuilt a **slot-b-only** super, so preservation of the other
slot is **unproven** — the simulator marks this scenario *blocked*, not passed.

## 2c. The patched-unlock lk is NOT backed up
`preserve-check` verifies the **stock** LK dumps (anti-brick restore) only. The
**patched** lk that provides the slot-b LK-only unlock is not in the backup set,
so its preservation is not established. Losing it loses the current unlock.

## 3. Real partition geometry is assumed, not read
`device-profile.json` uses representative partition sizes and the documented
super layout (single raw ~7 GiB VAB, groups `main_a`/`main_b`). The real GPT
offsets/sizes must be read from the device (read-only) and the plan re-validated
against them before any write. The simulator uses nominal sizes, not the live map.

## 4. The rebuilt slot-b super is referenced, not re-validated here
A complete slot-b super was built and round-trip validated by earlier scripts
(`scripts/build-lineage-super.py`, `validate-super.py`). This tool plans the
super write but does not itself rebuild or re-hash that multi-GB image end to
end. Re-run that validation and record the final super hash in the catalog
before relying on it.

## 5. Partitions without a stock rollback image
`md1img`, `tee`, `scp`, `sspm`, `spmfw`, `gz`, `logo` are written by the OTA but
have no stock rollback image on hand in the catalog (modem/TEE/firmware live in
the stock ROM's own images, intentionally excluded to preserve unlock). This
incomplete coverage is reported as a **blocking / unresolved** condition
(`rollback-plan` fails), not success. The first-line safety net is the untouched
**running slot** (left alone because the install targets the inactive slot). If a
firmware-layer partition is ever disturbed, recovery depends on the BROM backups +
stock ROM, a heavier physical-access path. Decide per-partition rollback before
writing any of these.

## 6. Device operations are only described
`set-active b`, the bootloader-mode physical flashes, and the super flash are
emitted as **planned** device operations (flagged `device_op`). They are not
executed and are not wired to any tool. Executing them is out of scope for this
phase and requires explicit per-`AGENTS.md`/`CLAUDE.md §2` approval, a
`HIGH_RISK_LOG.md` entry, battery ≥ 50 % / stable power, and a re-read of the
live unlock and slot state immediately beforehand.

## 7. Power / battery gate
Prior writes net-discharged the phone over the Pi USB path and a super flash
stopped mid-write on low battery. A stable charging/power path must be
established and confirmed before any real write; this tool cannot assess it.

## Summary
Offline readiness: **PASS**. Real-world readiness: **blocked** on (1) a trusted
signature/AVB verification path, (2) the on-device AVB orange-state boot test,
(3) reading and re-validating the live partition geometry, and (4) explicit
approval + a confirmed power path. Items 4–7 are planning/operational; items 1–3
are the substantive technical blockers.
