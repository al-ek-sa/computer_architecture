from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .memory import MemoryFault


class ByteMemory(Protocol):

    def read_bytes(self, address: int, size: int) -> bytes: ...

    def write_bytes(self, address: int, payload: bytes) -> None: ...


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
    memory: object
    line_size: int = 16
    line_count: int = 16
    hit_latency: int = 1
    memory_latency: int = 10
    lines: list[CacheLine] = field(init=False)
    stats: CacheStats = field(default_factory=CacheStats)
    log: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.line_size < 4 or self.line_size & (self.line_size - 1):
            raise ValueError("line_size must be a power of two and at least 4")
        if self.line_count <= 0:
            raise ValueError("line_count must be positive")
        if self.hit_latency <= 0 or self.memory_latency <= 0:
            raise ValueError("cache latencies must be positive")
        self.lines = [
            CacheLine(data=bytearray(self.line_size))
            for _ in range(self.line_count)
        ]

    def _check_range(self, address: int, size: int) -> None:
        if size not in (1, 2, 4):
            raise MemoryFault(f"unsupported cached access size: {size}")
        if address < 0 or address + size > (1 << 32):
            raise MemoryFault(f"cache address range out of range: {address:#x}")

    def _backing_read(self, address: int, size: int) -> bytes:
        if isinstance(self.memory, bytearray):
            if address + size > len(self.memory):
                raise MemoryFault(f"backing memory read out of range: {address:#x}")
            return bytes(self.memory[address:address + size])
        reader = getattr(self.memory, "read_bytes", None)
        if reader is None:
            raise TypeError("cache backing memory must provide read_bytes/write_bytes")
        return reader(address, size)

    def _backing_write(self, address: int, payload: bytes) -> None:
        if isinstance(self.memory, bytearray):
            if address + len(payload) > len(self.memory):
                raise MemoryFault(f"backing memory write out of range: {address:#x}")
            self.memory[address:address + len(payload)] = payload
            return
        writer = getattr(self.memory, "write_bytes", None)
        if writer is None:
            raise TypeError("cache backing memory must provide read_bytes/write_bytes")
        writer(address, payload)

    def _parts(self, address: int) -> tuple[int, int, int, int]:
        if not 0 <= address < (1 << 32):
            raise MemoryFault(f"cache address out of range: {address:#x}")
        block, offset = divmod(address, self.line_size)
        index = block % self.line_count
        tag = block // self.line_count
        return block, index, tag, offset

    def _writeback(self, index: int) -> None:
        line = self.lines[index]
        if line.valid and line.dirty:
            old_block = line.tag * self.line_count + index
            self._backing_write(old_block * self.line_size, bytes(line.data))
            self.stats.writebacks += 1
            line.dirty = False
            self.log.append(f"WRITEBACK index={index}")

    def _load_line(self, block: int, index: int, tag: int) -> None:
        line = self.lines[index]
        self._writeback(index)
        base = block * self.line_size
        line.data[:] = self._backing_read(base, self.line_size)
        line.tag = tag
        line.valid = True
        line.dirty = False

    def _access_chunk(self, address: int, payload: bytes | None, size: int) -> tuple[bytes, bool, int]:
        block, index, tag, offset = self._parts(address)
        line = self.lines[index]
        hit = line.valid and line.tag == tag
        if hit:
            self.stats.hits += 1
            self.log.append(f"HIT address={address:#010x}")
        else:
            self.stats.misses += 1
            self.log.append(f"MISS address={address:#010x}")
            self._load_line(block, index, tag)

        if payload is None:
            result = bytes(line.data[offset:offset + size])
        else:
            line.data[offset:offset + size] = payload
            line.dirty = True
            result = b""
        return result, hit, self.hit_latency if hit else self.memory_latency

    def read(self, address: int, size: int = 4) -> CacheAccess:
        self._check_range(address, size)
        result = bytearray()
        remaining = size
        cursor = address
        total_latency = 0
        all_hits = True
        while remaining:
            offset = cursor % self.line_size
            count = min(remaining, self.line_size - offset)
            chunk, hit, latency = self._access_chunk(cursor, None, count)
            result.extend(chunk)
            all_hits &= hit
            total_latency += latency
            cursor += count
            remaining -= count
        return CacheAccess(int.from_bytes(result, "little"), total_latency, all_hits)

    def write(self, address: int, value: int, size: int = 4) -> CacheAccess:
        self._check_range(address, size)
        payload = (value & ((1 << (size * 8)) - 1)).to_bytes(size, "little")
        remaining = size
        cursor = address
        source_offset = 0
        total_latency = 0
        all_hits = True
        while remaining:
            offset = cursor % self.line_size
            count = min(remaining, self.line_size - offset)
            _, hit, latency = self._access_chunk(
                cursor, payload[source_offset:source_offset + count], count
            )
            all_hits &= hit
            total_latency += latency
            cursor += count
            source_offset += count
            remaining -= count
        return CacheAccess(None, total_latency, all_hits)

    def flush(self) -> None:
        for index in range(self.line_count):
            self._writeback(index)

    def invalidate(self, address: int, *, writeback: bool = True) -> None:
        _, index, tag, _ = self._parts(address)
        line = self.lines[index]
        if line.valid and line.tag == tag:
            if line.dirty and writeback:
                self._writeback(index)
            line.valid = False
            line.dirty = False

    def clear(self, *, writeback: bool = True) -> None:
        if writeback:
            self.flush()
        for line in self.lines:
            line.valid = False
            line.dirty = False

    def clear_stats(self) -> None:
        self.stats = CacheStats()
        self.log.clear()