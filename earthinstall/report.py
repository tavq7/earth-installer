"""Assemble the offline pipeline results into a readiness report (Markdown)."""

from __future__ import annotations

import datetime as _dt


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def build_report(results: dict) -> str:
    """results: mapping of component-name -> component result dict."""
    order = ["image-verification", "device-compat", "partition-compat",
             "preservation", "install-plan", "block-device-simulation",
             "rollback-plan"]
    comps = [results[k] for k in order if k in results]
    overall = all(c.get("pass") for c in comps)

    now = _dt.date.today().isoformat()
    lines: list[str] = []
    lines.append("# Earth Upgrade & Rescue — offline readiness report")
    lines.append("")
    lines.append(f"Generated: {now} · tool phase: OFFLINE (no device access)")
    lines.append("")
    lines.append(f"**Overall offline gate: {_status(overall)}**")
    lines.append("")
    lines.append("| Component | Result |")
    lines.append("|---|---|")
    for c in comps:
        lines.append(f"| {c['component']} | {_status(c.get('pass'))} |")
    lines.append("")

    # Per-component detail.
    iv = results.get("image-verification")
    if iv:
        lines.append("## Image verification")
        lines.append(f"- counts: {iv['counts']}")
        for r in iv["results"]:
            lines.append(f"  - {r['role']}/{r['name']}: {r['status']}")
        lines.append(f"- {iv['note']}")
        lines.append("")

    for key, title in [("device-compat", "Device compatibility"),
                       ("partition-compat", "Partition compatibility")]:
        c = results.get(key)
        if not c:
            continue
        lines.append(f"## {title}")
        for chk in c.get("checks", []):
            lines.append(f"- {_status(chk['pass'])} {chk['check']}: {chk['detail']}")
        if "rows" in c:
            mapped = sum(1 for r in c["rows"] if r["kind"] != "unmapped")
            prot = sum(1 for r in c["rows"] if r["protected"])
            lines.append(f"- {mapped}/{len(c['rows'])} OTA partitions map to a known "
                         f"device partition; {prot} protected (excluded)")
            lines.append(f"- super target group: {c.get('super_group_for_target_slot')}")
        for prob in c.get("problems", []):
            lines.append(f"- PROBLEM: {prob}")
        lines.append("")

    pr = results.get("preservation")
    if pr:
        lines.append("## Preservation (LK + preloader)")
        lines.append(f"- verified roles: {pr['verified_roles']}")
        if pr["missing_or_bad_roles"]:
            lines.append(f"- MISSING/BAD: {pr['missing_or_bad_roles']}")
        lines.append("")

    pl = results.get("install-plan")
    if pl:
        lines.append("## Install plan (dry-run)")
        lines.append(f"- target slot: {pl['target_slot']} (active {pl['active_slot_preserved']} preserved)")
        lines.append(f"- physical writes: {len(pl['physical_writes'])}, "
                     f"dynamic writes: {len(pl['dynamic_writes'])}, "
                     f"skipped (protected/excluded): {len(pl['skipped'])}")
        for inv in pl["invariants"]:
            lines.append(f"  - invariant: {inv}")
        lines.append("")

    sim = results.get("block-device-simulation")
    if sim:
        lines.append("## Block-device simulation")
        for s in sim["scenarios"]:
            lines.append(f"- {_status(s['pass'])} {s['scenario']}: {s['detail']}")
        lines.append("")

    ro = results.get("rollback-plan")
    if ro:
        lines.append("## Rollback plan")
        lines.append(f"- first-line safety net: untouched active slot {ro['active_slot_is_safety_net']!r}")
        if ro["uncovered_partitions"]:
            lines.append(f"- partitions with NO stock rollback image: {ro['uncovered_partitions']}")
        lines.append("")

    return "\n".join(lines) + "\n"
