# Earth Upgrade & Rescue

Offline-first install & recovery **planner/verifier** for the personally owned
Redmi 12C (`earth`, MediaTek MT6768/MT6769). It prepares and proves a LineageOS
24.0 install to the inactive A/B slot while preserving the LK-only unlock.

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
