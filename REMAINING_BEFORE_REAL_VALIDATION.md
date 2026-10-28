# What remains before real-world validation

The offline tool in this directory passes its full offline gate (image hashes,
device/partition compatibility, LK+preloader preservation, dry-run plan,
block-device simulation, rollback plan). That result is necessary but **not
sufficient** to install on the phone. Everything below is still open and cannot
be closed offline. Nothing here should be read as clearance to flash.

## 1. Cryptographic trust is not established
The tool checks that images match recorded SHA-256 values. It does **not** verify
the LineageOS signing chain, the OTA `payload.bin` signature, or AVB/vbmeta
descriptors against a trusted key. `custom-build/verification.json` already
records this as the open gate ("CUSTOM OTA BLOCKED ON ACCEPTED SIGNING PATH").
Hash equality only proves the bytes are the ones we previously saw.

## 2. The central unknown is unchanged: AVB orange-state boot under the LK-only unlock
The install targets slot `b`, which carries the patched LK (LK-only unlock). It
is still unproven on this unit that a LineageOS slot-b boot/super passes
verified-boot in that state and actually boots. This is an **on-device** test
(`PLAN_Y3_RESEARCH.md` names it as the one remaining unknown). The simulation
models block writes and interruption; it does not model AVB, dm-verity, or the
boot-control hand-off. Note also that the profile's `active_slot: a` is an
**offline test fixture**, not a verified current device state — the last observed
running slot was **B**. The real active/current slot must be re-read from the
device (read-only) before any write; the simulation uses `a` only to model the
documented fallback so it can prove the running slot is never written.

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
the stock ROM's own images, intentionally excluded to preserve unlock). The
first-line safety net remains the untouched active slot `a`. If a firmware-layer
partition is ever disturbed, recovery depends on the BROM backups + stock ROM,
which is a heavier, physical-access path. Decide per-partition rollback before
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
