from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .isa import INPUT_DATA, OUTPUT_DATA, CYCLE_COUNTER, INPUT_STATUS, MMIO_END, WORD_MASK


class DeviceError(RuntimeError):
    """Device protocol violation."""


class DeviceOverrun(DeviceError):
    """A new input byte arrived before the previous byte was consumed."""


@dataclass(slots=True)
class InputDevice:
    value: int | None = None
    interrupt_callback: Callable[[], None] | None = None

    @property
    def ready(self) -> bool:
        return self.value is not None

    def arrive(self, value: int) -> None:
        if self.value is not None:
            raise DeviceOverrun(f"input overrun: unread byte {self.value:#04x}")
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


@dataclass(slots=True)
class OutputDevice:
    output: bytearray = field(default_factory=bytearray)

    def write(self, value: int) -> None:
        self.output.append(value & 0xFF)

    def get_bytes(self) -> bytes:
        return bytes(self.output)

    def get_text(self, encoding: str = "utf-8") -> str:
        return self.get_bytes().decode(encoding, errors="replace")


@dataclass(slots=True)
class CycleCounter:
    cycles: int = 0

    def tick(self) -> None:
        self.cycles = (self.cycles + 1) & WORD_MASK

    def read(self) -> int:
        return self.cycles


@dataclass(slots=True)
class MMIODeviceBus:
    input: InputDevice = field(default_factory=InputDevice)
    output: OutputDevice = field(default_factory=OutputDevice)
    timer: CycleCounter = field(default_factory=CycleCounter)

    def contains(self, address: int) -> bool:
        return 0 <= address < MMIO_END

    def read(self, address: int, size: int = 4) -> int:
        if size not in (1, 4):
            raise DeviceError(f"unsupported MMIO read size: {size}")
        if address == INPUT_DATA:
            return self.input.read_data()
        if address == INPUT_STATUS:
            return self.input.read_status()
        if address == CYCLE_COUNTER:
            return self.timer.read()
        if address == OUTPUT_DATA:
            return 0
        raise DeviceError(f"unmapped MMIO read at {address:#010x}")

    def write(self, address: int, value: int, size: int = 4) -> None:
        if size not in (1, 4):
            raise DeviceError(f"unsupported MMIO write size: {size}")
        if address == OUTPUT_DATA:
            self.output.write(value)
            return
        if address in (INPUT_DATA, INPUT_STATUS, CYCLE_COUNTER):
            raise DeviceError(f"MMIO register {address:#010x} is read-only")
        raise DeviceError(f"unmapped MMIO write at {address:#010x}")