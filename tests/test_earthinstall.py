"""Offline unit tests. No device access, no network. Run: python3 -m pytest tests -q
or: python3 tests/test_earthinstall.py (falls back to a plain runner)."""

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
    safety.assert_no_device_tooling()


def test_forbidden_module_detected():
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
    pkg = ROOT / "earthinstall"
    offenders = []
    needles = ("import subprocess", "subprocess.", "os.system(", "os.popen(",
               "os.exec", "pty.spawn")
    for f in pkg.glob("*.py"):
        code = "\n".join(ln for ln in f.read_text().splitlines()
                         if not ln.lstrip().startswith("#"))
        if any(n in code for n in needles):
            offenders.append(f.name)
    assert not offenders, f"device-capable calls present in {offenders}"


# ---- fixture / slot evidence ---------------------------------------------

def test_active_slot_is_fixture_not_evidence():
    assert PROFILE.active_slot_is_fixture is True
    running = PROFILE.resolve_running_slot()
    # Default resolution must NOT come from the fixture active_slot; it uses the
    # last_confirmed_running record (slot b), and is not fresh.
    assert running["slot"] == "b"
    assert running["is_fresh"] is False
    assert running["is_fixture"] is False


def test_fresh_evidence_overrides():
    r = PROFILE.resolve_running_slot("a", "fastboot getvar current-slot 2026-10-28")
    assert r["slot"] == "a" and r["is_fresh"] is True and r["is_fixture"] is False


# REGRESSION: incorrect active slot — target must not equal the running slot,
# and fixture/non-fresh evidence must block device-readiness.
def test_regression_target_equals_running_slot_blocks():
    pl = plan.build_plan(PROFILE, CATALOG)  # running defaults to b; target is b
    assert pl["target_slot"] == "b" and pl["running_slot"]["slot"] == "b"
    assert pl["device_ready"] is False
    assert any("target slot" in b and "running slot" in b
               for b in pl["device_ready_blockers"])
    # compat's inactive-slot check must fail on this collision.
    dc = compat.check_device(PROFILE, CATALOG)
    chk = {c["check"]: c["pass"] for c in dc["checks"]}
    assert chk["target-slot-is-inactive"] is False


def test_plan_not_device_ready_even_with_fresh_good_slot():
    # Fresh evidence putting running on 'a' (target b) removes the slot collision,
    # but shared-super preservation is still unproven, so NOT device-ready.
    pl = plan.build_plan(PROFILE, CATALOG, "a", "live read 2026-10-28")
    assert not any("target slot" in b and "running slot" in b
                   for b in pl["device_ready_blockers"])
    assert pl["device_ready"] is False
    assert any("super" in b for b in pl["device_ready_blockers"])


# ---- compat ---------------------------------------------------------------

def test_device_compat_nonslot_checks_pass():
    dc = compat.check_device(PROFILE, CATALOG)
    for c in dc["checks"]:
        if c["check"] != "target-slot-is-inactive":
            assert c["pass"], c


def test_partition_compat_passes_and_protects():
    res = compat.check_partitions(PROFILE, CATALOG)
    assert res["pass"], res["problems"]
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


def test_protected_partitions_are_lk_and_preloader():
    assert PROFILE.protected_partition_names() == {"lk", "preloader"}


# ---- preservation ---------------------------------------------------------

def test_preserve_reports_lk_unlock_caveat():
    res = preserve.check_backups(PROFILE)
    assert res["covers_patched_unlock_lk"] is False
    assert res["lk_unlock_caveat"]
    for r in res["results"]:
        assert r["status"] in ("ok", "missing", "hash-mismatch")


# REGRESSION: missing artifacts must be reported as missing, never faked ok.
def test_regression_missing_artifacts_reported():
    pr = preserve.check_backups(PROFILE)
    iv = images.verify_catalog(CATALOG, max_bytes=1)  # force skip/missing
    # In the standalone repo the referenced files are absent.
    assert not pr["pass"] or all(
        r["status"] != "ok" for r in iv["results"])  # evidence not fabricated
    results = _full_results(max_bytes=1)
    gates = report.compute_gates(results)
    assert gates["evidence_incomplete"] is True
    assert gates["installation_ready"] is False


# ---- plan structural ------------------------------------------------------

def test_plan_excludes_protected_and_aligns():
    pl = plan.build_plan(PROFILE, CATALOG)
    written = {w["ota_partition"] for w in pl["physical_writes"] + pl["dynamic_writes"]}
    assert "lk" not in written and "preloader_raw" not in written
    assert pl["structurally_valid"] is True


# ---- block-device simulation ---------------------------------------------

def test_sim_boundary_scenarios_pass_and_super_blocked():
    pl = plan.build_plan(PROFILE, CATALOG)
    res = blocksim.run_scenarios(PROFILE, pl)
    assert not res["failed_scenarios"], res["failed_scenarios"]
    # Shared-super preservation is unproven -> blocked, so overall not pass.
    assert res["has_blocked"] is True
    assert "shared-super-preserves-running-slot" in res["blocked_scenarios"]
    assert res["pass"] is False


# REGRESSION: shared super is ONE physical partition; raw rewrite preservation
# of the other slot must be unproven (blocked), not silently passed.
def test_regression_shared_super_single_region_and_blocked():
    dev = blocksim.SimDevice.from_profile(PROFILE)
    # Exactly one super region, shared, with no per-slot super_a/super_b.
    assert "super" in dev.regions and dev.regions["super"].shared
    assert "super_a" not in dev.regions and "super_b" not in dev.regions
    assert PROFILE.super_shared is True
    assert PROFILE.super_preserves_other_slot == "unproven"


def test_sim_protected_write_raises():
    dev = blocksim.SimDevice.from_profile(PROFILE)
    try:
        dev.write("lk", dev.block_size)
        assert False
    except blocksim.ProtectedWriteError:
        pass


def test_sim_interruption_leaves_incomplete():
    dev = blocksim.SimDevice.from_profile(PROFILE, super_size=10 * (1 << 30))
    reg = dev.regions["super"]
    try:
        dev.write("super", reg.size, fail_after_chunk=3, chunk=1 << 30)
        assert False, "should interrupt"
    except blocksim.Interrupted as exc:
        assert exc.chunk_index == 3
        assert not reg.complete


# REGRESSION: oversize image must raise, never truncate via min().
def test_regression_oversize_image_raises():
    dev = blocksim.SimDevice.from_profile(PROFILE)
    size = dev.regions[f"boot_{dev.target_slot}"].size
    try:
        dev.write("boot", size + dev.block_size)  # from offset 0, too big
        assert False, "oversize should raise"
    except blocksim.OversizeImageError:
        pass
    # And _do_write must not truncate: a bloated OTA entry raises, not silently fits.
    bloated = {"ota_partition": "boot", "size": size + dev.block_size}
    try:
        blocksim._do_write(dev, bloated, PROFILE)
        assert False, "_do_write should raise on oversize"
    except blocksim.OversizeImageError:
        pass


def test_sim_unaligned_oob_overlap():
    dev = blocksim.SimDevice.from_profile(PROFILE)
    bs = dev.block_size
    try:
        dev.write("boot", bs + 1); assert False
    except blocksim.BoundaryError:
        pass
    try:
        dev.write("boot", bs, offset=dev.regions[f"boot_{dev.target_slot}"].size)
        assert False
    except blocksim.BoundaryError:
        pass
    dev.write("dtbo", bs, offset=0)
    try:
        dev.write("dtbo", bs, offset=0); assert False
    except blocksim.BoundaryError:
        pass


def test_sim_non_target_slot_write_rejected():
    dev = blocksim.SimDevice.from_profile(PROFILE)
    try:
        dev.write("boot", dev.block_size, slot=dev.other_slot)
        assert False
    except blocksim.ProtectedWriteError:
        pass


# ---- rollback -------------------------------------------------------------

# REGRESSION: incomplete rollback coverage must not report pass=True.
def test_regression_incomplete_rollback_blocks():
    res = rollback.build_rollback(PROFILE, CATALOG)
    assert res["uncovered_partitions"], "expected uncovered firmware partitions"
    assert res["coverage_complete"] is False
    assert res["unresolved"] is True
    assert res["pass"] is False


def test_rollback_safety_net_is_running_slot_not_fixture():
    res = rollback.build_rollback(PROFILE, CATALOG)
    running = PROFILE.resolve_running_slot()["slot"]
    assert res["active_slot_is_safety_net"] == running   # 'b', not fixture 'a'
    assert res["active_slot_is_safety_net"] != PROFILE.active_slot
    assert len(res["recovery_tiers"]) >= 3


# ---- gates / report -------------------------------------------------------

def test_gates_planning_valid_but_never_install_ready():
    results = _full_results(max_bytes=1200000000)
    gates = report.compute_gates(results)
    assert gates["planning_ok"] is True            # model is coherent
    assert gates["installation_ready"] is False    # never asserted true
    assert gates["device_ready"] is False
    assert gates["super_preserves_running_slot"] is False
    assert gates["rollback_coverage_complete"] is False
    assert gates["signatures_established"] is False


def test_report_builds_markdown():
    results = _full_results(max_bytes=1)
    results["_gates"] = report.compute_gates(results)
    md = report.build_report(results)
    assert "Earth Upgrade & Rescue" in md
    assert "NOT ESTABLISHED" in md
    assert "shared-super-preserves-running-slot" in md


# ---- images (synthetic) ---------------------------------------------------

def test_verify_catalog_detects_hash_and_missing():
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


# ---- helpers --------------------------------------------------------------

def _full_results(max_bytes=None):
    pl = plan.build_plan(PROFILE, CATALOG)
    return {
        "image-verification": images.verify_catalog(CATALOG, max_bytes=max_bytes),
        "device-compat": compat.check_device(PROFILE, CATALOG),
        "partition-compat": compat.check_partitions(PROFILE, CATALOG),
        "preservation": preserve.check_backups(PROFILE),
        "install-plan": pl,
        "block-device-simulation": blocksim.run_scenarios(PROFILE, pl),
        "rollback-plan": rollback.build_rollback(PROFILE, CATALOG),
    }


def _run_plain():
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
