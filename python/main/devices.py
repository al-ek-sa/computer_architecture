from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .isa import (
    CYCLE_COUNTER,
    INPUT_DATA,
    INPUT_STATUS,
    MMIO_END,
    OUTPUT_DATA,
    WORD_MASK,
    WORD_SIZE,
)


class DeviceError(RuntimeError):
    """Invalid device access."""


class DeviceOverrun(DeviceError):
    """Input arrived while the one-byte input register was still occupied."""


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
        if not 0 <= value <= WORD_MASK:
            raise DeviceError("input value must be in the 32-bit unsigned range")
        if self.ready:
            raise DeviceOverrun("input register is already occupied")

        self.value = value & 0xFF
        if self.interrupt_callback is not None:
            self.interrupt_callback()

    def read_data(self) -> int:
        if self.value is None:
            return 0
        value = self.value
        self.value = None
        return value

    def read_status(self) -> int:
        return int(self.ready)

    def reset(self) -> None:
        self.value = None


@dataclass(slots=True)
class OutputDevice:
    buffer: bytearray = field(default_factory=bytearray)

    def write(self, value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise DeviceError("output value must be an integer")
        if not 0 <= value <= WORD_MASK:
            raise DeviceError("output value must be in the 32-bit unsigned range")
        self.buffer.append(value & 0xFF)

    def get_bytes(self) -> bytes:
        return bytes(self.buffer)

    def getvalue(self) -> bytes:
        return self.get_bytes()

    def get_text(self, encoding: str = "utf-8", errors: str = "replace") -> str:
        return self.get_bytes().decode(encoding, errors)

    def reset(self) -> None:
        self.buffer.clear()


@dataclass(slots=True)
class CycleCounter:
    cycles: int = 0

    def tick(self) -> None:
        self.cycles = (self.cycles + 1) & WORD_MASK

    def advance(self, count: int = 1) -> None:
        if isinstance(count, bool) or not isinstance(count, int):
            raise DeviceError("cycle count must be an integer")
        if count < 0:
            raise DeviceError("cycle count must not be negative")
        self.cycles = (self.cycles + count) & WORD_MASK

    def read(self) -> int:
        return self.cycles

    def reset(self) -> None:
        self.cycles = 0


@dataclass(slots=True)
class MMIODeviceBus:
    input: InputDevice = field(default_factory=InputDevice)
    output: OutputDevice = field(default_factory=OutputDevice)
    timer: CycleCounter = field(default_factory=CycleCounter)

    def contains(self, address: int) -> bool:
        return (
            not isinstance(address, bool)
            and isinstance(address, int)
            and 0 <= address < MMIO_END
        )

    def contains_range(self, address: int, size: int) -> bool:
        if isinstance(address, bool) or not isinstance(address, int):
            return False
        if isinstance(size, bool) or not isinstance(size, int):
            return False
        if address < 0 or size <= 0:
            return False
        return address < MMIO_END and address + size <= MMIO_END

    def _validate_access(self, address: int, size: int) -> None:
        if isinstance(address, bool) or not isinstance(address, int):
            raise DeviceError("MMIO address must be an integer")
        if isinstance(size, bool) or not isinstance(size, int):
            raise DeviceError("MMIO access size must be an integer")
        if size not in (1, WORD_SIZE):
            raise DeviceError(f"unsupported MMIO access size: {size}")
        if address not in (INPUT_DATA, OUTPUT_DATA, CYCLE_COUNTER, INPUT_STATUS):
            raise DeviceError(f"unmapped MMIO access: {address:#x}")
        if address < 0 or address + size > MMIO_END:
            raise DeviceError(f"MMIO access out of range: {address:#x}")
        if size == WORD_SIZE and address % WORD_SIZE:
            raise DeviceError(f"unaligned MMIO word access: {address:#x}")

    def read(self, address: int, size: int = WORD_SIZE) -> int:
        self._validate_access(address, size)

        if address == INPUT_DATA:
            value = self.input.read_data()
        elif address == INPUT_STATUS:
            value = self.input.read_status()
        elif address == OUTPUT_DATA:
            value = 0
        elif address == CYCLE_COUNTER:
            value = self.timer.read()
        else:
            raise DeviceError(f"unmapped MMIO read: {address:#x}")

        return value & (0xFF if size == 1 else WORD_MASK)

    def write(self, address: int, value: int, size: int = WORD_SIZE) -> None:
        self._validate_access(address, size)
        if isinstance(value, bool) or not isinstance(value, int):
            raise DeviceError("MMIO write value must be an integer")
        if not 0 <= value <= WORD_MASK:
            raise DeviceError("MMIO write value must be in the 32-bit unsigned range")

        if address == OUTPUT_DATA:
            self.output.write(value)
            return
        if address in (INPUT_DATA, INPUT_STATUS, CYCLE_COUNTER):
            raise DeviceError(f"MMIO register is read-only: {address:#x}")
        raise DeviceError(f"unmapped MMIO write: {address:#x}")

    def reset(self) -> None:
        self.input.reset()
        self.output.reset()
        self.timer.reset()
