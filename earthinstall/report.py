"""Assemble the offline pipeline results into a readiness report (Markdown).

Three tiers are kept strictly separate and never conflated:
  1. Fixture/planning validation  — does the offline model hold together?
  2. Artifact verification        — are the referenced images present and correct?
  3. Real-world readiness         — never asserted true by this tool.
"""

from __future__ import annotations

import datetime as _dt


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def compute_gates(results: dict) -> dict:
    dc = results["device-compat"]
    pc = results["partition-compat"]
    pr = results["preservation"]
    pl = results["install-plan"]
    sim = results["block-device-simulation"]
    rb = results["rollback-plan"]
    iv = results["image-verification"]

    # Tier 1: planning/model validity (no external artifacts required).
    dc_planning = all(c["pass"] for c in dc.get("checks", [])
                      if c["check"] != "target-slot-is-inactive")
    planning_ok = (dc_planning and pc["pass"] and pl.get("structurally_valid", False)
                   and not sim.get("failed_scenarios"))

    # Tier 2: artifact verification. A mismatch is a hard failure; a missing file
    # is incomplete evidence (blocks readiness, not a code defect).
    iv_statuses = [r.get("status") for r in iv.get("results", [])]
    pr_statuses = [r.get("status") for r in pr.get("results", [])]
    verification_failed = any(s in ("hash-mismatch", "size-mismatch") for s in iv_statuses) \
        or any(s == "hash-mismatch" for s in pr_statuses)
    evidence_incomplete = (not pr["pass"]) \
        or any(s in ("missing", "skipped-large") for s in iv_statuses) \
        or not any(s == "ok" for s in iv_statuses)

    # Tier 3: real-world readiness — composed, and gated additionally on a
    # signature/AVB trust path this tool never establishes.
    device_ready = bool(pl.get("device_ready"))
    super_preserved = not sim.get("has_blocked")
    rollback_complete = bool(rb.get("coverage_complete"))
    signatures_established = False  # not implemented; AVB/signing trust is open

    installation_ready = (planning_ok and device_ready and super_preserved
                          and rollback_complete and not verification_failed
                          and not evidence_incomplete and signatures_established)

    return {
        "planning_ok": planning_ok,
        "verification_failed": verification_failed,
        "evidence_incomplete": evidence_incomplete,
        "device_ready": device_ready,
        "super_preserves_running_slot": super_preserved,
        "rollback_coverage_complete": rollback_complete,
        "signatures_established": signatures_established,
        "installation_ready": installation_ready,
    }


def build_report(results: dict) -> str:
    gates = results.get("_gates") or compute_gates(results)
    pl = results["install-plan"]
    sim = results["block-device-simulation"]
    rb = results["rollback-plan"]
    pr = results["preservation"]

    now = _dt.date.today().isoformat()
    L: list[str] = []
    L.append("# Earth Upgrade & Rescue — offline readiness report")
    L.append("")
    L.append(f"Generated: {now} · tool phase: OFFLINE (no device access)")
    L.append("")
    L.append("## Readiness tiers (kept separate)")
    L.append(f"- Tier 1 — fixture/planning validation: **{_status(gates['planning_ok'])}**")
    L.append(f"- Tier 2 — artifact verification: "
             f"{'FAILED' if gates['verification_failed'] else ('INCOMPLETE' if gates['evidence_incomplete'] else 'PASS')}")
    L.append(f"- Tier 3 — real-world installation readiness: "
             f"**NOT ESTABLISHED** (this tool never asserts it)")
    L.append("")
    L.append("### Why real-world readiness is not established")
    L.append(f"- device-ready (fresh slot evidence, target≠running): {_status(gates['device_ready'])}")
    L.append(f"- shared-super preserves running slot: {_status(gates['super_preserves_running_slot'])}")
    L.append(f"- rollback coverage complete: {_status(gates['rollback_coverage_complete'])}")
    L.append(f"- signature/AVB trust established: {_status(gates['signatures_established'])} (not implemented)")
    L.append(f"- artifact verification clean & complete: "
             f"{_status(not gates['verification_failed'] and not gates['evidence_incomplete'])}")
    L.append("")

    # Component table.
    order = ["image-verification", "device-compat", "partition-compat",
             "preservation", "install-plan", "block-device-simulation", "rollback-plan"]
    L.append("| Component | Result |")
    L.append("|---|---|")
    for k in order:
        c = results.get(k)
        if c:
            L.append(f"| {c['component']} | {_status(c.get('pass'))} |")
    L.append("")

    # Install plan + device readiness.
    L.append("## Install plan (dry-run)")
    rs = pl.get("running_slot", {})
    L.append(f"- target slot: {pl['target_slot']}; running slot: {rs.get('slot')} "
             f"(source: {rs.get('source')}; fresh={rs.get('is_fresh')}, fixture={rs.get('is_fixture')})")
    L.append(f"- device_ready: **{pl.get('device_ready')}**")
    for b in pl.get("device_ready_blockers", []):
        L.append(f"  - BLOCKER: {b}")
    L.append("")

    # Simulation.
    L.append("## Block-device simulation")
    for s in sim["scenarios"]:
        tag = "BLOCKED" if s["blocked"] else _status(s["pass"])
        L.append(f"- {tag} {s['scenario']}: {s['detail']}")
    if sim.get("blocked_scenarios"):
        L.append(f"- blocked (unproven): {sim['blocked_scenarios']}")
    L.append("")

    # Preservation.
    L.append("## Preservation (LK + preloader)")
    L.append(f"- verified roles: {pr['verified_roles']}")
    if pr["missing_or_bad_roles"]:
        L.append(f"- MISSING/BAD: {pr['missing_or_bad_roles']}")
    L.append(f"- covers stock-LK restore: {pr.get('covers_stock_lk')}")
    L.append(f"- covers PATCHED-unlock lk: {pr.get('covers_patched_unlock_lk')} "
             f"(the patched-unlock lk is NOT in this backup set)")
    L.append("")

    # Rollback.
    L.append("## Rollback plan")
    L.append(f"- coverage complete: {rb.get('coverage_complete')} (unresolved={rb.get('unresolved')})")
    if rb.get("uncovered_partitions"):
        L.append(f"- partitions with NO stock rollback image: {rb['uncovered_partitions']}")
    L.append("")

    iv = results.get("image-verification")
    if iv:
        L.append("## Image verification")
        L.append(f"- counts: {iv['counts']}")
        L.append(f"- {iv['note']}")
        L.append("")

    return "\n".join(L) + "\n"
