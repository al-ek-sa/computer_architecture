from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .isa import IMEM_SIZE, WORD_SIZE, WORD_MASK, MMIO_END


class MemoryErrorBase(RuntimeError):
    """Base class for memory errors."""


class MemoryFault(MemoryErrorBase):
    """Invalid, unaligned, or unmapped memory access."""


@dataclass(slots=True)
class InstructionMemory:
    size: int = IMEM_SIZE
    _bytes: bytearray = field(init=False)

    def __post_init__(self) -> None:
        if self.size <= 0:
            raise ValueError("instruction memory size must be positive")
        self._bytes = bytearray(self.size)

    def load(self, address: int, payload: bytes) -> None:
        end = address + len(payload)
        if address < 0 or end > self.size:
            raise MemoryFault(f"instruction segment [{address:#x}, {end:#x}) out of range")
        self._bytes[address:end] = payload

    def fetch_word(self, address: int) -> int:
        if address & (WORD_SIZE - 1):
            raise MemoryFault(f"unaligned instruction address: {address:#x}")
        if address < 0 or address + WORD_SIZE > self.size:
            raise MemoryFault(f"instruction address out of range: {address:#x}")
        return int.from_bytes(self._bytes[address:address + WORD_SIZE], "little")

    def read(self, address: int, size: int) -> bytes:
        if address < 0 or size < 0 or address + size > self.size:
            raise MemoryFault("instruction memory read out of range")
        return bytes(self._bytes[address:address + size])


@dataclass(slots=True)
class SparseDataMemory:
    address_bits: int = 32
    page_bits: int = 12
    _pages: dict[int, bytearray] = field(default_factory=dict)

    @property
    def address_limit(self) -> int:
        return 1 << self.address_bits

    @property
    def page_size(self) -> int:
        return 1 << self.page_bits

    def _check_range(self, address: int, size: int) -> None:
        if size < 0 or address < 0 or address + size > self.address_limit:
            raise MemoryFault(f"data address range [{address:#x}, {address + size:#x}) out of range")

    def _page(self, page_number: int, *, create: bool) -> bytearray | None:
        page = self._pages.get(page_number)
        if page is None and create:
            page = bytearray(self.page_size)
            self._pages[page_number] = page
        return page

    def read_bytes(self, address: int, size: int) -> bytes:
        self._check_range(address, size)
        result = bytearray(size)
        cursor = 0
        while cursor < size:
            current = address + cursor
            page_number, offset = divmod(current, self.page_size)
            count = min(size - cursor, self.page_size - offset)
            page = self._page(page_number, create=False)
            if page is not None:
                result[cursor:cursor + count] = page[offset:offset + count]
            cursor += count
        return bytes(result)

    def write_bytes(self, address: int, payload: bytes) -> None:
        self._check_range(address, len(payload))
        cursor = 0
        while cursor < len(payload):
            current = address + cursor
            page_number, offset = divmod(current, self.page_size)
            count = min(len(payload) - cursor, self.page_size - offset)
            page = self._page(page_number, create=True)
            assert page is not None
            page[offset:offset + count] = payload[cursor:cursor + count]
            cursor += count

    def read(self, address: int, size: int) -> int:
        if size not in (1, 2, 4):
            raise MemoryFault(f"unsupported read size: {size}")
        return int.from_bytes(self.read_bytes(address, size), "little")

    def write(self, address: int, value: int, size: int) -> None:
        if size not in (1, 2, 4):
            raise MemoryFault(f"unsupported write size: {size}")
        self.write_bytes(address, (value & ((1 << (size * 8)) - 1)).to_bytes(size, "little"))

    def load_segments(self, segments: Iterable[tuple[int, bytes]]) -> None:
        for address, payload in segments:
            if address < MMIO_END:
                raise MemoryFault("program data may not overwrite MMIO registers")
            self.write_bytes(address, payload)

    def allocated_pages(self) -> int:
        return len(self._pages)


@dataclass(slots=True)
class HarvardMemory:
    instruction: InstructionMemory = field(default_factory=InstructionMemory)
    data: SparseDataMemory = field(default_factory=SparseDataMemory)

    def load_segments(self, segments: dict[str, list[tuple[int, bytes]]]) -> None:
        for section, items in segments.items():
            if section == "text":
                for address, payload in items:
                    self.instruction.load(address, payload)
            else:
                self.data.load_segments(items)