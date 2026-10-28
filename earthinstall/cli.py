"""Command-line interface. Offline only; refuses if device tooling is present."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, compat, config, images, plan, preserve, report, rollback, safety


def _emit(obj: dict, outfile: str | None):
    text = json.dumps(obj, indent=2)
    if outfile:
        p = safety.write_output(outfile, text + "\n")
        print(f"written: {p}")
    else:
        print(text)


def _load():
    return config.load_profile(), config.load_catalog()


def cmd_verify_images(args):
    _, catalog = _load()
    res = images.verify_catalog(catalog, max_bytes=args.max_bytes)
    _emit(res, args.out)
    return 0 if res["pass"] else 2


def cmd_check_compat(args):
    profile, catalog = _load()
    dev = compat.check_device(profile, catalog)
    part = compat.check_partitions(profile, catalog)
    res = {"device-compat": dev, "partition-compat": part,
           "pass": dev["pass"] and part["pass"]}
    _emit(res, args.out)
    return 0 if res["pass"] else 2


def cmd_preserve_check(args):
    profile, _ = _load()
    res = preserve.check_backups(profile)
    _emit(res, args.out)
    return 0 if res["pass"] else 2


def cmd_plan(args):
    profile, catalog = _load()
    res = plan.build_plan(profile, catalog)
    _emit(res, args.out)
    return 0 if res["pass"] else 2


def cmd_simulate(args):
    from . import blocksim
    profile, catalog = _load()
    pl = plan.build_plan(profile, catalog)
    res = blocksim.run_scenarios(profile, pl)
    _emit(res, args.out)
    return 0 if res["pass"] else 2


def cmd_rollback(args):
    profile, catalog = _load()
    res = rollback.build_rollback(profile, catalog)
    _emit(res, args.out)
    return 0 if res["pass"] else 2


def cmd_all(args):
    from . import blocksim
    profile, catalog = _load()
    results = {}
    results["image-verification"] = images.verify_catalog(catalog, max_bytes=args.max_bytes)
    results["device-compat"] = compat.check_device(profile, catalog)
    results["partition-compat"] = compat.check_partitions(profile, catalog)
    results["preservation"] = preserve.check_backups(profile)
    pl = plan.build_plan(profile, catalog)
    results["install-plan"] = pl
    results["block-device-simulation"] = blocksim.run_scenarios(profile, pl)
    results["rollback-plan"] = rollback.build_rollback(profile, catalog)

    md = report.build_report(results)
    safety.write_output("readiness-report.json", json.dumps(results, indent=2) + "\n")
    rp = safety.write_output("readiness-report.md", md)
    print(md)
    print(f"written: {rp}")
    # Overall gate excludes image-verification missing files (artifacts may be
    # gitignored / absent); planning + simulation + preservation must pass.
    core = ["device-compat", "partition-compat", "preservation",
            "install-plan", "block-device-simulation", "rollback-plan"]
    return 0 if all(results[k]["pass"] for k in core) else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="earth-installer",
        description="Offline-first installer/recovery planner for Redmi 12C (earth). "
                    "Performs NO device operations.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_out(sp):
        sp.add_argument("--out", help="write JSON result to out/<name> instead of stdout")

    sp = sub.add_parser("verify-images", help="hash catalog images, compare to recorded sha256")
    sp.add_argument("--max-bytes", type=int, default=None,
                    help="skip hashing files larger than this many bytes")
    add_out(sp); sp.set_defaults(func=cmd_verify_images)

    sp = sub.add_parser("check-compat", help="device + partition compatibility")
    add_out(sp); sp.set_defaults(func=cmd_check_compat)

    sp = sub.add_parser("preserve-check", help="verify LK(both slots)+preloader backups")
    add_out(sp); sp.set_defaults(func=cmd_preserve_check)

    sp = sub.add_parser("plan", help="dry-run A/B + dynamic-partition install plan")
    add_out(sp); sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("simulate", help="simulated block-device interruption/boundary tests")
    add_out(sp); sp.set_defaults(func=cmd_simulate)

    sp = sub.add_parser("rollback-plan", help="recovery + rollback planning")
    add_out(sp); sp.set_defaults(func=cmd_rollback)

    sp = sub.add_parser("all", help="run the whole offline pipeline + write readiness report")
    sp.add_argument("--max-bytes", type=int, default=None)
    sp.set_defaults(func=cmd_all)
    return p


def main(argv=None) -> int:
    safety.assert_no_device_tooling()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
