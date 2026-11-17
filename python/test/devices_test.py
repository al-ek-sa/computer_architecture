import pytest
from main.devices import (
    CycleCounter,
    DeviceError,
    DeviceOverrun,
    InputDevice,
    MMIODeviceBus,
    OutputDevice,
)
from main.isa import CYCLE_COUNTER, INPUT_DATA, INPUT_STATUS, OUTPUT_DATA, WORD_MASK


def test_input_device_holds_byte_until_consumed() -> None:
    device = InputDevice()
    device.arrive(ord("Q"))
    assert device.ready
    assert device.read_status() == 1
    assert device.read_data() == ord("Q")
    assert not device.ready
    assert device.read_data() == 0


def test_input_device_triggers_interrupt_callback() -> None:
    calls = []
    device = InputDevice(interrupt_callback=lambda: calls.append("irq"))
    device.arrive(65)
    assert calls == ["irq"]


def test_input_device_rejects_overrun_instead_of_queueing() -> None:
    device = InputDevice()
    device.arrive(65)
    with pytest.raises(DeviceOverrun):
        device.arrive(66)
    assert device.read_data() == 65


def test_input_device_masks_value_to_byte() -> None:
    device = InputDevice()
    device.arrive(0x141)
    assert device.read_data() == 0x41


def test_output_device_collects_bytes_and_decodes_text() -> None:
    device = OutputDevice()
    device.write(ord("O"))
    device.write(ord("K"))
    assert device.get_bytes() == b"OK"
    assert device.get_text() == "OK"


def test_output_device_keeps_only_low_byte() -> None:
    device = OutputDevice()
    device.write(0x141)
    assert device.get_bytes() == b"A"


def test_cycle_counter_increments_and_wraps_32_bits() -> None:
    counter = CycleCounter(cycles=WORD_MASK)
    counter.tick()
    assert counter.read() == 0


def test_mmio_bus_decodes_input_status_data_and_output() -> None:
    bus = MMIODeviceBus()
    assert bus.contains(INPUT_DATA)
    assert bus.contains(OUTPUT_DATA)
    assert not bus.contains(0x10)
    bus.input.arrive(90)
    assert bus.read(INPUT_STATUS) == 1
    assert bus.read(INPUT_DATA, size=1) == 90
    bus.write(OUTPUT_DATA, ord("Z"), size=1)
    assert bus.output.get_text() == "Z"


def test_mmio_bus_exposes_cycle_counter() -> None:
    bus = MMIODeviceBus()
    bus.timer.tick()
    bus.timer.tick()
    assert bus.read(CYCLE_COUNTER) == 2


def test_mmio_rejects_writes_to_read_only_registers() -> None:
    bus = MMIODeviceBus()
    for address in (INPUT_DATA, INPUT_STATUS, CYCLE_COUNTER):
        with pytest.raises(DeviceError, match="read-only"):
            bus.write(address, 1)


def test_mmio_rejects_unmapped_addresses_and_widths() -> None:
    bus = MMIODeviceBus()
    with pytest.raises(DeviceError, match="unmapped"):
        bus.read(0x10)
    with pytest.raises(DeviceError, match="unsupported"):
        bus.read(INPUT_DATA, size=2)
