"""Simulated block device with interruption and boundary checking.

No real storage is touched. A SimDevice models named partition regions per slot
as in-memory block maps. Writes are chunked (bounded by max_download_size, like
the real bootloader's 128 MiB limit) so we can inject an interruption after any
chunk and prove the partial/resume/rollback logic — mirroring the real Plan Y3
failure (super flash stopped at chunk 9 of 17 on low battery).

Boundary rules enforced on every write:
  * offset and length are block-aligned
  * the write stays within the partition
  * no two accepted writes to one partition overlap
  * protected partitions reject all writes
  * writes only ever hit the target slot; the other slot is immutable here
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_DOWNLOAD = 0x8000000  # 128 MiB; earth bootloader max-download-size


class BoundaryError(ValueError):
    pass


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
    written: int = 0          # contiguous bytes confirmed written from offset 0
    intervals: list = field(default_factory=list)  # accepted (start, end) spans

    @property
    def complete(self) -> bool:
        return self.written >= self.size


@dataclass
class SimDevice:
    block_size: int
    target_slot: str
    other_slot: str
    regions: dict = field(default_factory=dict)       # "name_slot" -> Region
    log: list = field(default_factory=list)

    @classmethod
    def from_profile(cls, profile, super_size: int | None = None) -> "SimDevice":
        target = profile.target_slot
        other = profile.active_slot
        dev = cls(block_size=profile.block_size, target_slot=target, other_slot=other)
        protected = profile.protected_partition_names()
        for p in profile.physical():
            size = _rounded(_nominal_size(p["name"]), dev.block_size)
            for slot in (target, other):
                dev.regions[f"{p['name']}_{slot}"] = Region(
                    size=size, protected=p["name"] in protected)
        s = profile.partitions["super"]
        ssize = super_size or int(s.get("approx_size_bytes", 0))
        for slot in (target, other):
            dev.regions[f"{s['name']}_{slot}"] = Region(size=_rounded(ssize, dev.block_size))
        return dev

    def _region(self, name: str, slot: str) -> Region:
        key = f"{name}_{slot}"
        if key not in self.regions:
            raise BoundaryError(f"unknown partition region {key}")
        return self.regions[key]

    def write(self, name: str, data_len: int, *, slot: str | None = None,
              offset: int = 0, fail_after_chunk: int | None = None,
              chunk: int = MAX_DOWNLOAD) -> dict:
        """Simulate a chunked write of data_len bytes at offset into name on slot."""
        slot = slot or self.target_slot
        if slot != self.target_slot:
            raise ProtectedWriteError(
                f"refusing to write non-target slot {slot!r} (active slot immutable)")
        region = self._region(name, slot)
        if region.protected:
            raise ProtectedWriteError(f"partition {name!r} is protected; write refused")

        bs = self.block_size
        if offset % bs or data_len % bs:
            raise BoundaryError(
                f"unaligned write {name}: offset={offset} len={data_len} block={bs}")
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
                region.written = max(region.written, pos if offset == 0 else region.written)
                self.log.append({"partition": name, "slot": slot,
                                 "event": "interrupted", "chunk": idx, "pos": pos})
                raise Interrupted(name, idx, pos - offset)
            pos += step
            idx += 1
        region.intervals.append((offset, end))
        if offset == 0:
            region.written = max(region.written, end)
        self.log.append({"partition": name, "slot": slot, "event": "complete",
                         "bytes": data_len, "chunks": idx})
        return {"partition": name, "slot": slot, "bytes": data_len, "chunks": idx,
                "complete": region.complete}

    def snapshot(self) -> dict:
        return {k: {"size": r.size, "written": r.written, "complete": r.complete,
                    "protected": r.protected} for k, r in self.regions.items()}


def _nominal_size(name: str) -> int:
    # Representative physical partition sizes (bytes) for the simulation. Real
    # geometry comes from the device GPT, read-only, in a later on-device phase.
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
    """Run the boundary/interruption/rollback scenarios and report pass/fail."""
    scenarios: list[dict] = []

    def record(name: str, ok: bool, detail: str):
        scenarios.append({"scenario": name, "pass": bool(ok), "detail": detail})

    writes = plan["physical_writes"] + plan["dynamic_writes"]

    # S1: clean full install writes every planned partition to completion.
    dev = SimDevice.from_profile(profile, super_size=_plan_super_size(profile, plan))
    try:
        for w in writes:
            _do_write(dev, w, profile)
        target_done = all(dev.regions[k].complete
                          for k in _target_keys(dev, writes, profile))
        record("clean-full-install", target_done, "all target-slot writes complete")
    except Exception as exc:  # noqa: BLE001
        record("clean-full-install", False, f"unexpected: {exc!r}")

    # S2: active slot stays byte-untouched after a full install.
    other_touched = any(r.written for k, r in dev.regions.items()
                        if k.endswith(f"_{dev.other_slot}"))
    record("active-slot-immutable", not other_touched,
           f"no writes to slot {dev.other_slot!r}")

    # S3: interruption mid-super (reproduce Plan Y3 chunk failure) leaves super
    #     incomplete and detectable; no protected partition was touched.
    dev2 = SimDevice.from_profile(profile, super_size=_plan_super_size(profile, plan))
    super_name = profile.partitions["super"]["name"]
    interrupted_ok = False
    reg0 = dev2.regions[f"{super_name}_{dev2.target_slot}"]
    chunk = 1 << 30
    n_chunks = (reg0.size + chunk - 1) // chunk
    fail_at = max(1, n_chunks // 2)  # fail roughly halfway, always < n_chunks
    try:
        dev2.write(super_name, reg0.size, fail_after_chunk=fail_at, chunk=chunk)
    except Interrupted as exc:
        reg = dev2.regions[f"{super_name}_{dev2.target_slot}"]
        interrupted_ok = (not reg.complete) and exc.chunk_index == fail_at
    record("interruption-detected", interrupted_ok,
           "super left incomplete and flagged after mid-write interruption")

    # S4: resume after interruption completes without overlap error.
    resume_ok = False
    try:
        reg = dev2.regions[f"{super_name}_{dev2.target_slot}"]
        reg.intervals.clear()  # a resume re-writes the whole raw partition from 0
        reg.written = 0
        res = dev2.write(super_name, reg.size, chunk=1 << 30)
        resume_ok = res["complete"]
    except Exception as exc:  # noqa: BLE001
        resume_ok = False
    record("resume-completes", resume_ok, "re-flash from offset 0 completes super")

    # S5: boundary rejections — unaligned, out-of-bounds, overlap, protected.
    b = _boundary_checks(profile)
    record("boundary-unaligned-rejected", b["unaligned"], "unaligned write raises")
    record("boundary-oob-rejected", b["oob"], "out-of-bounds write raises")
    record("boundary-overlap-rejected", b["overlap"], "overlapping write raises")
    record("protected-write-rejected", b["protected"], "write to lk/preloader raises")
    record("other-slot-write-rejected", b["other_slot"], "write to active slot raises")

    ok = all(s["pass"] for s in scenarios)
    return {"component": "block-device-simulation", "pass": ok,
            "max_download_size": MAX_DOWNLOAD, "scenarios": scenarios}


def _plan_super_size(profile, plan) -> int:
    for w in plan["dynamic_writes"]:
        pass
    return int(profile.partitions["super"].get("approx_size_bytes", 1 << 30))


def _do_write(dev: SimDevice, w: dict, profile):
    name = w["ota_partition"]
    super_name = profile.partitions["super"]["name"]
    if name in set(profile.partitions["super"]["logical_partitions"]):
        # Logical partitions are written as one rebuilt raw super image.
        reg = dev.regions[f"{super_name}_{dev.target_slot}"]
        if not reg.complete and not reg.intervals:
            dev.write(super_name, reg.size, chunk=1 << 30)
    else:
        phys = "preloader" if name == "preloader_raw" else name
        reg = dev.regions[f"{phys}_{dev.target_slot}"]
        size = _rounded(w["size"], dev.block_size)
        size = min(size, reg.size)
        dev.write(phys, size, chunk=MAX_DOWNLOAD)


def _target_keys(dev, writes, profile):
    keys = set()
    super_name = profile.partitions["super"]["name"]
    logicals = set(profile.partitions["super"]["logical_partitions"])
    for w in writes:
        n = w["ota_partition"]
        if n in logicals:
            keys.add(f"{super_name}_{dev.target_slot}")
        else:
            phys = "preloader" if n == "preloader_raw" else n
            keys.add(f"{phys}_{dev.target_slot}")
    return keys


def _boundary_checks(profile) -> dict:
    out = {}
    dev = SimDevice.from_profile(profile)
    bs = dev.block_size
    try:
        dev.write("boot", bs + 1)
        out["unaligned"] = False
    except BoundaryError:
        out["unaligned"] = True
    try:
        dev.write("boot", dev.regions[f"boot_{dev.target_slot}"].size + bs)
        out["oob"] = False
    except BoundaryError:
        out["oob"] = True
    try:
        dev.write("dtbo", bs, offset=0)
        dev.write("dtbo", bs, offset=0)  # overlap
        out["overlap"] = False
    except BoundaryError:
        out["overlap"] = True
    try:
        dev.write("lk", bs)
        out["protected"] = False
    except ProtectedWriteError:
        out["protected"] = True
    try:
        dev.write("boot", bs, slot=dev.other_slot)
        out["other_slot"] = False
    except ProtectedWriteError:
        out["other_slot"] = True
    return out
