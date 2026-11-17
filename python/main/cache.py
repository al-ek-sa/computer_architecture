from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .isa import MMIO_END
from .memory import MemoryFault


class ByteMemory(Protocol):
    @property
    def address_limit(self) -> int: ...

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
        if self.accesses == 0:
            return 0.0
        return self.hits / self.accesses


@dataclass(slots=True)
class DataCache:
    memory: ByteMemory
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

        if self.line_size > MMIO_END or MMIO_END % self.line_size != 0:
            raise ValueError(
                "line_size must divide MMIO_END to prevent cache lines "
                "from overlapping MMIO"
            )

        if self.line_count <= 0:
            raise ValueError("line_count must be positive")
        if self.hit_latency <= 0 or self.memory_latency <= 0:
            raise ValueError("cache latencies must be positive")
        self.lines = [
            CacheLine(data=bytearray(self.line_size)) for _ in range(self.line_count)
        ]

    @property
    def address_limit(self) -> int:
        limit = getattr(self.memory, "address_limit", None)
        if limit is not None:
            return int(limit)
        if isinstance(self.memory, bytearray):
            return len(self.memory)
        return 1 << 32

    def _check_range(self, address: int, size: int) -> None:
        if size not in (1, 2, 4):
            raise MemoryFault(f"unsupported cached access size: {size}")

        end = address + size

        if address < 0 or end > self.address_limit:
            raise MemoryFault(
                f"cache address range [{address:#x}, {end:#x}) out of range"
            )

        if address < MMIO_END:
            raise MemoryFault("MMIO accesses must bypass Data Cache")

    def _parts(
        self,
        address: int,
    ) -> tuple[int, int, int, int]:
        if not 0 <= address < (1 << 32):
            raise MemoryFault(f"cache address out of range: {address:#x}")

        block, offset = divmod(address, self.line_size)
        index = block % self.line_count
        tag = block // self.line_count
        return block, index, tag, offset

    def _backing_read(self, address: int, size: int) -> bytes:
        if isinstance(self.memory, bytearray):
            end = address + size

            if end > len(self.memory):
                raise MemoryFault(f"backing memory read out of range: {address:#x}")

            return bytes(self.memory[address:end])

        payload = self.memory.read_bytes(address, size)

        if len(payload) != size:
            raise MemoryFault(
                f"backing memory returned {len(payload)} bytes, expected {size}"
            )

        return payload

    def _backing_write(
        self,
        address: int,
        payload: bytes,
    ) -> None:
        if isinstance(self.memory, bytearray):
            end = address + len(payload)

            if end > len(self.memory):
                raise MemoryFault(f"backing memory write out of range: {address:#x}")

            self.memory[address:end] = payload
            return
        self.memory.write_bytes(address, payload)

    def _writeback(self, index: int) -> bool:
        line = self.lines[index]

        if not line.valid or not line.dirty:
            return False

        old_block = line.tag * self.line_count + index
        old_address = old_block * self.line_size

        self._backing_write(old_address, bytes(line.data))

        line.dirty = False
        self.stats.writebacks += 1

        self.log.append(f"WRITEBACK index={index} address={old_address:#010x}")

        return True

    def _load_line(
        self,
        block: int,
        index: int,
        tag: int,
    ) -> bool:
        line = self.lines[index]
        wrote_back = self._writeback(index)

        base_address = block * self.line_size

        line.data[:] = self._backing_read(
            base_address,
            self.line_size,
        )

        line.tag = tag
        line.valid = True
        line.dirty = False
        self.log.append(f"FILL index={index} address={base_address:#010x}")
        return wrote_back

    def _access_chunk(
        self,
        address: int,
        payload: bytes | None,
        size: int,
    ) -> tuple[bytes, bool, int]:
        block, index, tag, offset = self._parts(address)
        line = self.lines[index]
        hit = line.valid and line.tag == tag
        wrote_back = False
        if hit:
            self.stats.hits += 1
            self.log.append(f"HIT address={address:#010x}")
        else:
            self.stats.misses += 1
            self.log.append(f"MISS address={address:#010x}")

            wrote_back = self._load_line(
                block,
                index,
                tag,
            )

        if payload is None:
            result = bytes(line.data[offset : offset + size])
        else:
            line.data[offset : offset + size] = payload
            line.dirty = True
            result = b""

        latency = self.hit_latency if hit else self.memory_latency

        if wrote_back:
            latency += self.memory_latency
        return result, hit, latency

    def estimate_latency(self, address: int, size: int) -> int:
        self._check_range(address, size)
        remaining = size
        cursor = address
        total_latency = 0

        while remaining:
            offset = cursor % self.line_size
            count = min(
                remaining,
                self.line_size - offset,
            )

            block, index, tag, _ = self._parts(cursor)
            line = self.lines[index]
            if line.valid and line.tag == tag:
                total_latency += self.hit_latency
            else:
                total_latency += self.memory_latency

                if line.valid and line.dirty:
                    total_latency += self.memory_latency

            cursor += count
            remaining -= count

        return total_latency

    def read(
        self,
        address: int,
        size: int = 4,
    ) -> CacheAccess:
        self._check_range(address, size)
        result = bytearray()
        remaining = size
        cursor = address
        total_latency = 0
        all_hits = True
        while remaining:
            offset = cursor % self.line_size
            count = min(
                remaining,
                self.line_size - offset,
            )

            chunk, hit, latency = self._access_chunk(
                cursor,
                None,
                count,
            )

            result.extend(chunk)
            all_hits &= hit
            total_latency += latency
            cursor += count
            remaining -= count

        return CacheAccess(
            value=int.from_bytes(result, "little"),
            latency=total_latency,
            hit=all_hits,
        )

    def write(
        self,
        address: int,
        value: int,
        size: int = 4,
    ) -> CacheAccess:
        self._check_range(address, size)

        mask = (1 << (size * 8)) - 1
        payload = (value & mask).to_bytes(size, "little")

        remaining = size
        cursor = address
        source_offset = 0
        total_latency = 0
        all_hits = True
        while remaining:
            offset = cursor % self.line_size
            count = min(
                remaining,
                self.line_size - offset,
            )

            _, hit, latency = self._access_chunk(
                cursor,
                payload[source_offset : source_offset + count],
                count,
            )
            all_hits &= hit
            total_latency += latency
            cursor += count
            source_offset += count
            remaining -= count

        return CacheAccess(
            value=None,
            latency=total_latency,
            hit=all_hits,
        )

    def flush(self) -> None:
        for index in range(self.line_count):
            self._writeback(index)

    def invalidate(
        self,
        address: int,
        *,
        writeback: bool = True,
    ) -> None:
        _, index, tag, _ = self._parts(address)
        line = self.lines[index]

        if not line.valid or line.tag != tag:
            return

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
