"""Simulated block device with interruption and boundary checking.

No real storage is touched. A SimDevice models named partition regions as
in-memory block maps. Per-slot physical partitions (boot, dtbo, ...) exist once
per slot. The dynamic `super` partition is modelled as ONE shared physical
region (both slots' logical groups main_a/main_b live inside it), because that
is how earth is built: a raw rewrite of super replaces the whole physical
partition and therefore touches the other slot's logical data.

Writes are chunked (bounded by max_download_size, like the real bootloader's
128 MiB limit) so an interruption can be injected after any chunk, mirroring the
real Plan Y3 failure (super flash stopped at chunk 9 of 17 on low battery).

Boundary rules enforced on every write:
  * offset and length are block-aligned
  * the write stays within the partition (oversize raises, never truncates)
  * no two accepted writes to one partition overlap
  * protected partitions reject all writes
  * a per-slot partition rejects writes aimed at a non-target slot
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_DOWNLOAD = 0x8000000  # 128 MiB; earth bootloader max-download-size


class BoundaryError(ValueError):
    pass


class OversizeImageError(ValueError):
    """An image is larger than the partition region it targets. Never truncate."""


class ProtectedWriteError(RuntimeError):
    pass


class Interrupted(RuntimeError):
    def __init__(self, partition: str, chunk_index: int, bytes_written: int):
        super().__init__(f"interrupted writing {partition} at chunk {chunk_index}")
        self.partition = partition
        self.chunk_index = chunk_index
        self.bytes_written = bytes_written


@dataclass
class Region:
    size: int
    protected: bool = False
    shared: bool = False      # True for the single shared physical super
    written: int = 0
    intervals: list = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.written >= self.size


@dataclass
class SimDevice:
    block_size: int
    target_slot: str
    other_slot: str
    super_name: str = "super"
    regions: dict = field(default_factory=dict)
    log: list = field(default_factory=list)

    @classmethod
    def from_profile(cls, profile, super_size: int | None = None,
                     running_slot: str | None = None) -> "SimDevice":
        # Model BOTH physical slots. 'other' is the complement of the install
        # target, so the immutability check validates write mechanics regardless
        # of the (separately flagged) target==running collision.
        target = profile.target_slot
        other = next((s for s in profile.slots if s != target), target)
        s = profile.partitions["super"]
        dev = cls(block_size=profile.block_size, target_slot=target, other_slot=other,
                  super_name=s["name"])
        protected = profile.protected_partition_names()
        for p in profile.physical():
            size = _rounded(_nominal_size(p["name"]), dev.block_size)
            for slot in (target, other):
                dev.regions[f"{p['name']}_{slot}"] = Region(
                    size=size, protected=p["name"] in protected)
        ssize = super_size or int(s.get("approx_size_bytes", 0))
        # ONE shared physical super region (not per-slot).
        dev.regions[s["name"]] = Region(size=_rounded(ssize, dev.block_size), shared=True)
        return dev

    def _resolve(self, name: str, slot: str):
        key = f"{name}_{slot}"
        if key in self.regions:
            return key, self.regions[key], True   # per-slot
        if name in self.regions:
            return name, self.regions[name], False  # shared (super)
        raise BoundaryError(f"unknown partition region {name} (slot {slot})")

    def write(self, name: str, data_len: int, *, slot: str | None = None,
              offset: int = 0, fail_after_chunk: int | None = None,
              chunk: int = MAX_DOWNLOAD) -> dict:
        slot = slot or self.target_slot
        key, region, per_slot = self._resolve(name, slot)
        if per_slot and slot != self.target_slot:
            raise ProtectedWriteError(
                f"refusing to write non-target slot {slot!r} of {name!r}")
        if region.protected:
            raise ProtectedWriteError(f"partition {name!r} is protected; write refused")

        bs = self.block_size
        if offset % bs or data_len % bs:
            raise BoundaryError(
                f"unaligned write {name}: offset={offset} len={data_len} block={bs}")
        if offset == 0 and data_len > region.size:
            raise OversizeImageError(
                f"image for {name} is {data_len} B but partition is {region.size} B")
        end = offset + data_len
        if end > region.size:
            raise BoundaryError(
                f"out-of-bounds write {name}: [{offset},{end}) exceeds size {region.size}")
        for s, e in region.intervals:
            if offset < e and s < end:
                raise BoundaryError(f"overlapping write {name}: [{offset},{end}) vs [{s},{e})")

        pos = offset
        idx = 0
        while pos < end:
            step = min(chunk, end - pos)
            if fail_after_chunk is not None and idx == fail_after_chunk:
                self.log.append({"partition": name, "event": "interrupted",
                                 "chunk": idx, "pos": pos})
                raise Interrupted(name, idx, pos - offset)
            pos += step
            idx += 1
        region.intervals.append((offset, end))
        if offset == 0:
            region.written = max(region.written, end)
        self.log.append({"partition": name, "event": "complete",
                         "bytes": data_len, "chunks": idx})
        return {"partition": name, "bytes": data_len, "chunks": idx,
                "complete": region.complete, "shared": region.shared}

    def snapshot(self) -> dict:
        return {k: {"size": r.size, "written": r.written, "complete": r.complete,
                    "protected": r.protected, "shared": r.shared}
                for k, r in self.regions.items()}


def _nominal_size(name: str) -> int:
    sizes = {
        "boot": 67108864, "dtbo": 8388608, "vbmeta": 4096, "vbmeta_system": 4096,
        "vbmeta_vendor": 4096, "md1img": 63758336, "scp": 630784, "sspm": 507904,
        "spmfw": 53248, "gz": 2830336, "tee": 2560000, "logo": 331776,
        "lk": 1642496, "preloader": 311296,
    }
    return sizes.get(name, 4096)


def _rounded(n: int, bs: int) -> int:
    if n <= 0:
        return bs
    return ((n + bs - 1) // bs) * bs


def run_scenarios(profile, plan: dict) -> dict:
    """Run boundary/interruption/preservation scenarios. A 'blocked' scenario is
    an unproven safety property, reported distinctly from a plain failure."""
    scenarios: list[dict] = []
    running = plan.get("running_slot", {}).get("slot") or profile.resolve_running_slot()["slot"]

    def record(name, ok, detail, *, blocked=False):
        scenarios.append({"scenario": name, "pass": bool(ok),
                          "blocked": bool(blocked), "detail": detail})

    writes = plan["physical_writes"] + plan["dynamic_writes"]
    super_name = profile.partitions["super"]["name"]
    ssize = int(profile.partitions["super"].get("approx_size_bytes", 1 << 30))

    # S1: clean full install writes every planned partition to completion.
    dev = SimDevice.from_profile(profile, super_size=ssize, running_slot=running)
    try:
        for w in writes:
            _do_write(dev, w, profile)
        target_done = all(dev.regions[k].complete for k in _target_keys(dev, writes, profile))
        record("clean-full-install", target_done, "all target writes complete")
    except Exception as exc:  # noqa: BLE001
        record("clean-full-install", False, f"unexpected: {exc!r}")

    # S2: per-slot physical partitions of the running slot stay untouched.
    other_touched = any(r.written for k, r in dev.regions.items()
                        if k.endswith(f"_{dev.other_slot}") and not r.shared)
    record("running-slot-physical-immutable", not other_touched,
           f"no per-slot physical writes to running slot {dev.other_slot!r}")

    # S3: shared-super preservation of the running slot — BLOCKED (unproven).
    #     super is one physical partition; a raw rewrite overwrites both groups.
    proven = profile.super_preserves_other_slot == "proven"
    record("shared-super-preserves-running-slot", proven,
           "super is ONE shared physical partition; raw rewrite overwrites the "
           "running slot's logical group. Preservation is %r — rebuilt super not "
           "proven to carry slot %r's logicals (CLAUDE.md L328)."
           % (profile.super_preserves_other_slot, running),
           blocked=not proven)

    # S4: interruption mid-super leaves it incomplete and detectable.
    dev2 = SimDevice.from_profile(profile, super_size=ssize, running_slot=running)
    reg0 = dev2.regions[super_name]
    chunk = 1 << 30
    n_chunks = (reg0.size + chunk - 1) // chunk
    fail_at = max(1, n_chunks // 2)
    interrupted_ok = False
    try:
        dev2.write(super_name, reg0.size, fail_after_chunk=fail_at, chunk=chunk)
    except Interrupted as exc:
        interrupted_ok = (not reg0.complete) and exc.chunk_index == fail_at
    record("interruption-detected", interrupted_ok,
           "super left incomplete and flagged after mid-write interruption")

    # S5: resume after interruption completes.
    resume_ok = False
    try:
        reg0.intervals.clear(); reg0.written = 0
        resume_ok = dev2.write(super_name, reg0.size, chunk=chunk)["complete"]
    except Exception:  # noqa: BLE001
        resume_ok = False
    record("resume-completes", resume_ok, "re-flash from offset 0 completes super")

    # S6: boundary + oversize + protected rejections.
    b = _boundary_checks(profile, running)
    record("boundary-unaligned-rejected", b["unaligned"], "unaligned write raises")
    record("boundary-oob-rejected", b["oob"], "out-of-bounds write raises")
    record("oversize-image-rejected", b["oversize"],
           "image larger than partition raises OversizeImageError (no truncation)")
    record("boundary-overlap-rejected", b["overlap"], "overlapping write raises")
    record("protected-write-rejected", b["protected"], "write to lk/preloader raises")
    record("non-target-slot-write-rejected", b["other_slot"],
           "write to a non-target slot raises")

    blocked = [s["scenario"] for s in scenarios if s["blocked"]]
    failed = [s["scenario"] for s in scenarios if not s["pass"] and not s["blocked"]]
    return {"component": "block-device-simulation",
            "pass": not failed and not blocked,
            "has_blocked": bool(blocked),
            "blocked_scenarios": blocked,
            "failed_scenarios": failed,
            "max_download_size": MAX_DOWNLOAD,
            "scenarios": scenarios}


def _do_write(dev: SimDevice, w: dict, profile):
    name = w["ota_partition"]
    super_name = profile.partitions["super"]["name"]
    if name in set(profile.partitions["super"]["logical_partitions"]):
        reg = dev.regions[super_name]
        if not reg.complete and not reg.intervals:
            dev.write(super_name, reg.size, chunk=1 << 30)
    else:
        phys = "preloader" if name == "preloader_raw" else name
        key = f"{phys}_{dev.target_slot}"
        reg = dev.regions[key]
        size = _rounded(w["size"], dev.block_size)
        # No truncation: an oversize image is an explicit failure.
        dev.write(phys, size, chunk=MAX_DOWNLOAD)
        _ = reg


def _target_keys(dev, writes, profile):
    keys = set()
    super_name = profile.partitions["super"]["name"]
    logicals = set(profile.partitions["super"]["logical_partitions"])
    for w in writes:
        n = w["ota_partition"]
        if n in logicals:
            keys.add(super_name)
        else:
            phys = "preloader" if n == "preloader_raw" else n
            keys.add(f"{phys}_{dev.target_slot}")
    return keys


def _boundary_checks(profile, running_slot) -> dict:
    out = {}
    dev = SimDevice.from_profile(profile, running_slot=running_slot)
    bs = dev.block_size
    try:
        dev.write("boot", bs + 1); out["unaligned"] = False
    except BoundaryError:
        out["unaligned"] = True
    try:
        # offset write past the end -> out of bounds (not oversize-from-zero)
        dev.write("boot", bs, offset=dev.regions[f"boot_{dev.target_slot}"].size)
        out["oob"] = False
    except BoundaryError:
        out["oob"] = True
    try:
        dev.write("boot", dev.regions[f"boot_{dev.target_slot}"].size + bs)
        out["oversize"] = False
    except OversizeImageError:
        out["oversize"] = True
    try:
        dev.write("dtbo", bs, offset=0)
        dev.write("dtbo", bs, offset=0); out["overlap"] = False
    except BoundaryError:
        out["overlap"] = True
    try:
        dev.write("lk", bs); out["protected"] = False
    except ProtectedWriteError:
        out["protected"] = True
    try:
        dev.write("boot", bs, slot=dev.other_slot); out["other_slot"] = False
    except ProtectedWriteError:
        out["other_slot"] = True
    return out
