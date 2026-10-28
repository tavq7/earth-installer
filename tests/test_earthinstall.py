"""Offline unit tests. No device access, no network. Run: python3 -m pytest tests -q
or: python3 tests/test_earthinstall.py (falls back to a plain runner)."""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from earthinstall import (blocksim, compat, config, images, plan,  # noqa: E402
                          preserve, report, rollback, safety)

PROFILE = config.load_profile()
CATALOG = config.load_catalog()


# ---- safety ---------------------------------------------------------------

def test_no_device_tooling_passes_clean():
    safety.assert_no_device_tooling()  # no forbidden modules imported


def test_forbidden_module_detected(monkeypatch=None):
    import types
    sys.modules["mtkclient"] = types.ModuleType("mtkclient")
    try:
        try:
            safety.assert_no_device_tooling()
            assert False, "should have refused"
        except safety.SafetyViolation:
            pass
    finally:
        del sys.modules["mtkclient"]


def test_guard_output_path_rejects_outside():
    try:
        safety.guard_output_path("/etc/passwd")
        assert False, "should reject"
    except safety.SafetyViolation:
        pass
    inside = safety.OUTPUT_DIR / "x.json"
    assert safety.guard_output_path(inside) == inside.resolve()


def test_no_subprocess_in_package():
    # Audit: no package module should import subprocess/os.system device calls.
    pkg = ROOT / "earthinstall"
    offenders = []
    needles = ("import subprocess", "subprocess.", "os.system(", "os.popen(",
               "os.exec", "pty.spawn")
    for f in pkg.glob("*.py"):
        # Ignore comment-only lines so documentation mentioning these is allowed.
        code = "\n".join(ln for ln in f.read_text().splitlines()
                         if not ln.lstrip().startswith("#"))
        if any(n in code for n in needles):
            offenders.append(f.name)
    assert not offenders, f"device-capable calls present in {offenders}"


# ---- config / compat ------------------------------------------------------

def test_profile_target_slot_differs_from_active():
    assert PROFILE.target_slot != PROFILE.active_slot


def test_protected_partitions_are_lk_and_preloader():
    assert PROFILE.protected_partition_names() == {"lk", "preloader"}


def test_device_compat_passes():
    assert compat.check_device(PROFILE, CATALOG)["pass"]


def test_partition_compat_passes_and_protects():
    res = compat.check_partitions(PROFILE, CATALOG)
    assert res["pass"], res["problems"]
    # lk + preloader_raw must be present but not included.
    byname = {r["ota_partition"]: r for r in res["rows"]}
    assert byname["lk"]["protected"] and not byname["lk"]["included_in_install"]
    assert not byname["preloader_raw"]["included_in_install"]


def test_partition_compat_flags_protected_if_included():
    import copy
    bad = copy.deepcopy(CATALOG)
    for p in bad["ota_payload_partitions"]:
        if p["name"] == "lk":
            p["included"] = True
    res = compat.check_partitions(PROFILE, bad)
    assert not res["pass"]
    assert any("protected" in x for x in res["problems"])


# ---- preservation ---------------------------------------------------------

def test_preserve_check_runs_and_reports_roles():
    res = preserve.check_backups(PROFILE)
    assert set(res["required_roles"]) == {"lk_slot_a", "lk_slot_b", "preloader_boot1"}
    # Each result row has a status; no fabricated pass for missing files.
    for r in res["results"]:
        assert r["status"] in ("ok", "missing", "hash-mismatch")


# ---- plan -----------------------------------------------------------------

def test_plan_excludes_protected_and_aligns():
    pl = plan.build_plan(PROFILE, CATALOG)
    written = {w["ota_partition"] for w in pl["physical_writes"] + pl["dynamic_writes"]}
    assert "lk" not in written and "preloader_raw" not in written
    assert pl["target_slot"] == "b"
    assert pl["pass"]


# ---- block-device simulation ---------------------------------------------

def test_sim_all_scenarios_pass():
    pl = plan.build_plan(PROFILE, CATALOG)
    res = blocksim.run_scenarios(PROFILE, pl)
    failed = [s for s in res["scenarios"] if not s["pass"]]
    assert res["pass"], failed


def test_sim_protected_write_raises():
    dev = blocksim.SimDevice.from_profile(PROFILE)
    try:
        dev.write("lk", dev.block_size)
        assert False
    except blocksim.ProtectedWriteError:
        pass


def test_sim_interruption_leaves_incomplete():
    dev = blocksim.SimDevice.from_profile(PROFILE, super_size=10 * (1 << 30))
    key = f"super_{dev.target_slot}"
    try:
        dev.write("super", dev.regions[key].size, fail_after_chunk=8, chunk=1 << 30)
        assert False, "should interrupt"
    except blocksim.Interrupted as exc:
        assert exc.chunk_index == 8
        assert not dev.regions[key].complete


def test_sim_unaligned_and_oob_and_overlap():
    dev = blocksim.SimDevice.from_profile(PROFILE)
    bs = dev.block_size
    for call in [
        lambda: dev.write("boot", bs + 1),
        lambda: dev.write("boot", dev.regions[f"boot_{dev.target_slot}"].size + bs),
    ]:
        try:
            call(); assert False
        except blocksim.BoundaryError:
            pass
    dev.write("dtbo", bs, offset=0)
    try:
        dev.write("dtbo", bs, offset=0); assert False
    except blocksim.BoundaryError:
        pass


def test_sim_active_slot_immutable():
    dev = blocksim.SimDevice.from_profile(PROFILE)
    try:
        dev.write("boot", dev.block_size, slot=dev.other_slot)
        assert False
    except blocksim.ProtectedWriteError:
        pass


# ---- rollback / report ----------------------------------------------------

def test_rollback_has_active_slot_net_and_tiers():
    res = rollback.build_rollback(PROFILE, CATALOG)
    assert res["active_slot_is_safety_net"] == PROFILE.active_slot
    assert len(res["recovery_tiers"]) >= 3


def test_report_builds_markdown():
    results = {
        "device-compat": compat.check_device(PROFILE, CATALOG),
        "partition-compat": compat.check_partitions(PROFILE, CATALOG),
        "preservation": preserve.check_backups(PROFILE),
        "install-plan": plan.build_plan(PROFILE, CATALOG),
        "block-device-simulation": blocksim.run_scenarios(
            PROFILE, plan.build_plan(PROFILE, CATALOG)),
        "rollback-plan": rollback.build_rollback(PROFILE, CATALOG),
    }
    md = report.build_report(results)
    assert "Earth Upgrade & Rescue" in md and "Rollback plan" in md


# ---- images (synthetic, no real multi-GB files) ---------------------------

def test_verify_catalog_detects_hash_and_missing(tmp_path=None):
    import hashlib
    import tempfile
    d = Path(tempfile.mkdtemp())
    good = d / "good.img"
    good.write_bytes(b"hello")
    sha = hashlib.sha256(b"hello").hexdigest()
    cat = {
        "install_candidate": {"name": "good.img", "path": str(good),
                              "size": 5, "sha256": sha},
        "rollback_images": {"root": str(d), "entries": [
            {"name": "bad", "file": "bad.img", "size": 3, "sha256": "00" * 32},
            {"name": "absent", "file": "absent.img", "size": 1, "sha256": "11" * 32},
        ]},
    }
    (d / "bad.img").write_bytes(b"xxx")
    res = images.verify_catalog(cat)
    byname = {r["name"]: r for r in res["results"]}
    assert byname["good.img"]["status"] == "ok"
    assert byname["bad"]["status"] == "hash-mismatch"
    assert byname["absent"]["status"] == "missing"
    assert not res["pass"]


def _run_plain():
    """Minimal runner when pytest is unavailable."""
    g = globals()
    tests = [v for k, v in sorted(g.items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"PASS {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {exc!r}")
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_plain())
