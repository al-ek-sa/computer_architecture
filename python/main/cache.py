from __future__ import annotations

from dataclasses import dataclass, field
from .memory import SparseDataMemory, MemoryFault


@dataclass(frozen=True, slots=True)
class CacheAccess:
    value: int | None
    latency: int
    hit: bool


@dataclass(slots=True)
class CacheLine:
    valid: bool = False
    tag: int = 0
    data: bytearray = field(default_factory=bytearray)
    dirty: bool = False


@dataclass(slots=True)
class CacheStats:
    hits: int = 0
    misses: int = 0
    writebacks: int = 0

    @property
    def accesses(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / self.accesses if self.accesses else 0.0


@dataclass(slots=True)
class DataCache:
    memory: SparseDataMemory
    line_size: int = 16
    line_count: int = 16
    hit_latency: int = 1
    memory_latency: int = 10
    lines: list[CacheLine] = field(init=False)
    stats: CacheStats = field(default_factory=CacheStats)
    log: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.line_size <= 0 or self.line_count <= 0:
            raise ValueError("cache dimensions must be positive")
        if self.line_size & (self.line_size - 1):
            raise ValueError("line_size must be a power of two")
        self.lines = [CacheLine(data=bytearray(self.line_size)) for _ in range(self.line_count)]

    def _parts(self, address: int) -> tuple[int, int, int, int]:
        if not 0 <= address < (1 << 32):
            raise MemoryFault(f"cache address out of range: {address:#x}")
        block = address // self.line_size
        index = block % self.line_count
        tag = block // self.line_count
        offset = address % self.line_size
        return block, index, tag, offset

    def _writeback(self, index: int) -> None:
        line = self.lines[index]
        if line.valid and line.dirty:
            old_block = line.tag * self.line_count + index
            old_address = old_block * self.line_size
            self.memory.write_bytes(old_address, bytes(line.data))
            self.stats.writebacks += 1
            line.dirty = False

    def _fill(self, block: int, index: int, tag: int) -> None:
        line = self.lines[index]
        self._writeback(index)
        base = block * self.line_size
        line.data[:] = self.memory.read_bytes(base, self.line_size)
        line.tag = tag
        line.valid = True
        line.dirty = False

    def _get_line(self, address: int) -> tuple[CacheLine, int, bool]:
        block, index, tag, offset = self._parts(address)
        line = self.lines[index]
        hit = line.valid and line.tag == tag
        if hit:
            self.stats.hits += 1
            self.log.append(f"HIT  address={address:#010x}")
        else:
            self.stats.misses += 1
            self.log.append(f"MISS address={address:#010x}")
            self._fill(block, index, tag)
        return line, offset, hit

    def read(self, address: int, size: int = 4) -> CacheAccess:
        if size not in (1, 2, 4):
            raise MemoryFault(f"unsupported cached read size: {size}")
        line, offset, hit = self._get_line(address)
        if offset + size > self.line_size:
            # Simple and explicit handling for a request crossing a cache line.
            raw = self.memory.read_bytes(address, size)
            value = int.from_bytes(raw, "little")
            self.log.append(f"CROSS-LINE READ address={address:#010x}")
        else:
            value = int.from_bytes(line.data[offset:offset + size], "little")
        return CacheAccess(value, self.hit_latency if hit else self.memory_latency, hit)

    def write(self, address: int, value: int, size: int = 4) -> CacheAccess:
        if size not in (1, 2, 4):
            raise MemoryFault(f"unsupported cached write size: {size}")
        line, offset, hit = self._get_line(address)
        payload = (value & ((1 << (size * 8)) - 1)).to_bytes(size, "little")
        if offset + size > self.line_size:
            self.memory.write_bytes(address, payload)
            self.log.append(f"CROSS-LINE WRITE address={address:#010x}")
        else:
            line.data[offset:offset + size] = payload
            line.dirty = True
        return CacheAccess(None, self.hit_latency if hit else self.memory_latency, hit)

    def flush(self) -> None:
        for index in range(self.line_count):
            self._writeback(index)

    def invalidate(self, address: int) -> None:
        _, index, tag, _ = self._parts(address)
        line = self.lines[index]
        if line.valid and line.tag == tag:
            if line.dirty:
                self._writeback(index)
            line.valid = False

    def clear_stats(self) -> None:
        self.stats = CacheStats()
        self.log.clear()