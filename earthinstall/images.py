"""Image verification: hash files on disk, compare to the verified catalog."""

from __future__ import annotations

from pathlib import Path

from . import config
from .safety import hash_file


def verify_catalog(catalog: dict, *, max_bytes: int | None = None) -> dict:
    """Verify every catalog image present on disk against its recorded sha256.

    max_bytes: skip (status 'skipped-large') any file bigger than this, so a
    quick offline check can avoid hashing multi-GB images. None = hash all.
    Missing files are reported as 'missing', never fabricated as pass.
    """
    results: list[dict] = []

    def check(role: str, name: str, path: Path, size: int | None, expected: str):
        entry = {"role": role, "name": name, "path": str(path),
                 "expected_sha256": expected}
        if not path.exists():
            entry["status"] = "missing"
            results.append(entry)
            return
        actual_size = path.stat().st_size
        entry["actual_size"] = actual_size
        if size is not None and actual_size != size:
            entry["status"] = "size-mismatch"
            entry["expected_size"] = size
            results.append(entry)
            return
        if max_bytes is not None and actual_size > max_bytes:
            entry["status"] = "skipped-large"
            results.append(entry)
            return
        actual = hash_file(path)
        entry["actual_sha256"] = actual
        entry["status"] = "ok" if actual == expected else "hash-mismatch"
        results.append(entry)

    ic = catalog["install_candidate"]
    check("install_candidate", ic["name"], config.resolve(ic["path"]),
          ic.get("size"), ic["sha256"])

    rb = catalog.get("rollback_images", {})
    root = config.resolve(rb["root"]) if rb else None
    for e in rb.get("entries", []):
        check("rollback", e["name"], root / e["file"], e.get("size"), e["sha256"])

    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    present = [r for r in results if r["status"] not in ("missing", "skipped-large")]
    ok = present and all(r["status"] == "ok" for r in present)
    return {
        "component": "image-verification",
        "pass": bool(ok),
        "counts": counts,
        "results": results,
        "note": "cryptographic trust is NOT established by hash checks alone "
                "(see custom-build/verification.json). Signature acceptance is a "
                "separate, still-open gate.",
    }
