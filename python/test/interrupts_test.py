import pytest
from main.interrupts import InterruptController, InterruptError


def test_input_request_is_pending_until_accepted() -> None:
    controller = InterruptController(input_vector_address=0x100)
    controller.request_input()
    assert controller.input_pending
    assert controller.next_handler() == 0x100
    assert not controller.input_pending
    assert controller.active


def test_disabled_interrupt_is_not_accepted() -> None:
    controller = InterruptController(input_vector_address=0x100, enabled=False)
    controller.request_input()
    assert controller.next_handler() is None
    assert controller.input_pending


def test_active_interrupt_does_not_nest() -> None:
    controller = InterruptController(input_vector_address=0x100)
    controller.request_input()
    assert controller.next_handler() == 0x100
    controller.request_input()
    assert controller.next_handler() is None
    assert controller.input_pending


def test_zero_vector_does_not_accept_interrupt() -> None:
    controller = InterruptController(input_vector_address=0)
    controller.request_input()
    assert controller.next_handler() is None
    assert controller.input_pending


def test_complete_leaves_active_state() -> None:
    controller = InterruptController(input_vector_address=0x100)
    controller.request_input()
    controller.next_handler()
    controller.complete()
    assert not controller.active


def test_complete_without_active_interrupt_raises() -> None:
    with pytest.raises(InterruptError, match="outside"):
        InterruptController().complete()


def test_reset_clears_pending_and_active_state() -> None:
    controller = InterruptController(input_vector_address=0x100)
    controller.request_input()
    controller.next_handler()
    controller.reset()
    assert not controller.input_pending
    assert not controller.active
