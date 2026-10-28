# Earth Upgrade & Rescue

Offline-first install & recovery **planner/verifier** for the Xiaomi Redmi 12C
(`earth`, MediaTek MT6768/MT6769 / Helio G85). It plans and checks a LineageOS
**24.0 upgrade** to the inactive A/B slot.

**Observed state:** LineageOS **23.2 booted on slot B** (operator-confirmed). The
**24.0 upgrade is unvalidated** — not yet installed or booted. The recorded
`active_slot=a` in the profile is only a test **fixture**; the tool refuses to
use it as evidence of the running slot and will not call any plan device-ready
without fresh, explicitly-sourced slot evidence (and even then the shared-`super`
and signature blockers below remain).

> ## ⚠️ EXPERIMENTAL — not validated for general use
>
> This is a research/planning tool. Its installation and recovery functionality
> is **experimental and unproven on real hardware**. It is **not** safe,
> validated, or production-ready, and must not be treated as such. A passing
> offline run does **not** mean any install is safe to perform. Flashing a
> MediaTek device incorrectly can **permanently brick it**. Use at your own risk;
> the MIT license disclaims all warranty. See
> [`REMAINING_BEFORE_REAL_VALIDATION.md`](REMAINING_BEFORE_REAL_VALIDATION.md)
> for the substantive blockers that remain before any real-world use.

## What this is (and is not)

- **Is:** an offline planner/verifier. It hashes images, checks device and
  partition compatibility, confirms firmware-backup preservation, builds a
  dry-run install plan, simulates block-device writes (interruption + boundary
  handling), and plans rollback — producing a readiness report.
- **Is not:** a flasher. It never contacts, flashes, or reboots a phone, and it
  was authored for one specific personally owned unit. The device profile and
  observed state are **recorded evidence / test fixtures**, not live readings.

## The device

`earth` is the LineageOS codename shared by the Redmi 12C, Redmi 12C NFC, and
POCO C55 (MediaTek Helio G85, A/B virtual-A/B, dynamic `super` partition). The
profile here models one global Redmi 12C unit.

## Prerequisites

- Python 3 (standard library only; no dependencies, no network).
- To run `verify-images`/`preserve-check` meaningfully you must supply your own
  local copies of the referenced artifacts (LineageOS OTA, stock ROM images,
  firmware backups) at the paths in `config/*.json`; **none of those binaries
  are included in this repository** (by design — see Third-party artifacts).
  Without them, those checks honestly report `missing`.

## Current capabilities / limitations

Capabilities are the `Commands` below, all **offline**. Known limitations:
real AVB/signature trust is **not** established (hashes only); live partition
geometry is assumed, not read; `super` is one **shared physical partition**, so a
raw rewrite is **not proven** to preserve the other slot's logical data (the
simulator marks this *blocked*); the stored LK backups are **stock** dumps and do
**not** back up the patched-unlock lk on slot b; the simulator models block
writes, not AVB/dm-verity/boot-control; device operations are only *described*,
never executed; the `all` command never exits with an installation-ready verdict.
Full list in `REMAINING_BEFORE_REAL_VALIDATION.md`.

## This tool performs NO phone operations

In this development phase, real device actions are **impossible by construction**:

- No `adb`, `fastboot`, `fastbootd`, `mtkclient`, or any block-device access.
- No subprocess calls at all (audited by a test).
- No flashing, slot switching, or rebooting.
- It never writes to saved backups or original OTA packages (opened read-only).
- All generated output stays in `earth-installer/out/`.

It plans and simulates; it does not install. Passing the offline gate does **not**
mean the tool is safe to run against the device. See `REMAINING_BEFORE_REAL_VALIDATION.md`.

## Install (nothing to install)

Pure Python 3 standard library. No dependencies, no network.

## Usage

```
python3 run.py <command>            # or: python3 -m earthinstall <command>
```

Commands:

| Command | What it does |
|---|---|
| `verify-images` | Hash catalog images on disk, compare to recorded sha256. `--max-bytes N` skips files larger than N. |
| `check-compat` | Device + partition compatibility from recorded evidence. |
| `preserve-check` | Confirm both LK slots + preloader backups exist and match. |
| `plan` | Dry-run A/B + dynamic-partition install plan. |
| `simulate` | Simulated block-device interruption/boundary tests. |
| `rollback-plan` | Recovery + rollback tiers and per-partition coverage. |
| `all` | Run the whole pipeline; write `out/readiness-report.{md,json}`. |

Add `--out NAME` to any single command to write JSON into `out/NAME`.

## Tests

```
python3 tests/test_earthinstall.py      # plain runner (no pytest needed)
python3 -m pytest tests -q              # if pytest is available
```

## Configuration (reproducible, checked in)

- `config/device-profile.json` — earth partition/slot model, protected
  partitions, required backups. Evidence cited per field.
- `config/known-images.json` — verified image catalog (hashes transcribed from
  `builds.json`, `custom-build/verification.json`, `STOCK_ROLLBACK_MANIFEST.md`).

## Design

Layered package (`earthinstall/`): `safety` (sandbox invariants) → `config`
(load profile/catalog) → `images`/`compat`/`preserve`/`plan`/`blocksim`/
`rollback` (one responsibility each) → `report` (assemble) → `cli`.

Reuses completed project work rather than re-deriving it: OTA partition hashes
from the earlier offline payload parse, stock rollback hashes from the verified
stock ROM, LK/preloader/seccfg backups from the BROM capture.

## License and third-party artifacts

The code, tests, configuration, and documentation in this repository are
original work, licensed under [MIT](LICENSE) (© 2026 tavq7). The repository
ships **no third-party code and no firmware**:

- It contains only **SHA-256 hashes and metadata** describing LineageOS and
  Xiaomi stock images — facts about those files, not the files themselves.
- **LineageOS** images are distributed by the LineageOS project (predominantly
  Apache-2.0, with other licenses per component); **Xiaomi stock firmware** is
  proprietary. Neither is redistributed here. If you supply those artifacts
  locally, their own licenses govern them — not this repository's MIT license.
