from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

try:
    from .isa import (
        CYCLE_COUNTER,
        INPUT_DATA,
        INPUT_STATUS,
        MMIO_END,
        OUTPUT_DATA,
        WORD_MASK,
        WORD_SIZE,
    )
except ImportError:
    from isa import (
        CYCLE_COUNTER,
        INPUT_DATA,
        INPUT_STATUS,
        MMIO_END,
        OUTPUT_DATA,
        WORD_MASK,
        WORD_SIZE,
    )


class DeviceError(Exception):
    """Raised when an invalid device operation is performed."""


class DeviceOverrun(DeviceError):
    """Raised when input arrives while the input register is occupied."""


@dataclass(slots=True)
class InputDevice:
    value: int | None = None
    interrupt_callback: Callable[[], None] | None = None

    @property
    def ready(self) -> bool:
        return self.value is not None

    def arrive(self, value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise DeviceError("input value must be an integer")

        if self.value is not None:
            raise DeviceOverrun(
                f"input overrun: unread byte {self.value:#04x}"
            )

        self.value = value & 0xFF
        if self.interrupt_callback is not None:
            self.interrupt_callback()

    def read_data(self) -> int:
        if self.value is None:
            return 0

        result = self.value
        self.value = None
        return result

    def read_status(self) -> int:
        return int(self.ready)

    def reset(self) -> None:
        self.value = None


@dataclass(slots=True)
class OutputDevice:
    output: bytearray = field(default_factory=bytearray)

    def write(self, value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise DeviceError("output value must be an integer")

        self.output.append(value & 0xFF)

    def get_bytes(self) -> bytes:
        return bytes(self.output)

    def get_text(self, encoding: str = "utf-8") -> str:
        return self.output.decode(encoding, errors="replace")

    def reset(self) -> None:
        self.output.clear()


@dataclass(slots=True)
class CycleCounter:
    cycles: int = 0

    def tick(self) -> None:
        self.cycles = (self.cycles + 1) & WORD_MASK

    def advance(self, count: int) -> None:
        if isinstance(count, bool) or not isinstance(count, int):
            raise DeviceError("cycle count must be an integer")

        if count < 0:
            raise DeviceError("cycle count cannot be negative")

        self.cycles = (self.cycles + count) & WORD_MASK

    def read(self) -> int:
        return self.cycles & WORD_MASK

    def reset(self) -> None:
        self.cycles = 0


@dataclass(slots=True)
class MMIODeviceBus:
    input: InputDevice = field(default_factory=InputDevice)
    output: OutputDevice = field(default_factory=OutputDevice)
    timer: CycleCounter = field(default_factory=CycleCounter)

    def contains(self, address: int) -> bool:
        return isinstance(address, int) and 0 <= address < MMIO_END

    def contains_range(self, address: int, size: int) -> bool:
        if (
            isinstance(address, bool)
            or not isinstance(address, int)
            or isinstance(size, bool)
            or not isinstance(size, int)
        ):
            return False

        return (
                0 <= address < MMIO_END
                and size > 0
                and address + size <= MMIO_END
        )

    def _validate_access(self, address: int, size: int) -> None:
        if isinstance(address, bool) or not isinstance(address, int):
            raise DeviceError("MMIO address must be an integer")

        if isinstance(size, bool) or not isinstance(size, int):
            raise DeviceError("MMIO access width must be an integer")

        if size not in (1, WORD_SIZE):
            raise DeviceError(f"unsupported MMIO access width: {size}")

        if address < 0 or address > WORD_MASK:
            raise DeviceError(f"MMIO address is out of range: {address}")

        if address >= MMIO_END:
            raise DeviceError(f"unmapped MMIO address: {address:#010x}")

        if address + size > MMIO_END:
            raise DeviceError(
                f"MMIO access crosses region boundary: {address:#010x}"
            )

        if address % size != 0:
            raise DeviceError(f"unaligned MMIO access: {address:#010x}")

    def read(self, address: int, size: int = WORD_SIZE) -> int:
        self._validate_access(address, size)

        if address == INPUT_DATA:
            return self.input.read_data()
        if address == INPUT_STATUS:
            return self.input.read_status()
        if address == CYCLE_COUNTER:
            return self.timer.read()
        if address == OUTPUT_DATA:
            return 0

        raise DeviceError(f"unmapped MMIO read: {address:#010x}")

    def write(self, address: int, value: int, size: int = WORD_SIZE) -> None:
        self._validate_access(address, size)

        if isinstance(value, bool) or not isinstance(value, int):
            raise DeviceError("MMIO write value must be an integer")

        if address == OUTPUT_DATA:
            self.output.write(value)
            return
        if address in (INPUT_DATA, INPUT_STATUS, CYCLE_COUNTER):
            raise DeviceError(
                f"MMIO register is read-only: {address:#010x}"
            )

        raise DeviceError(f"unmapped MMIO write: {address:#010x}")

    def reset(self) -> None:
        self.input.reset()
        self.output.reset()
        self.timer.reset()