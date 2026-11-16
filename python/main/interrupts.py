from __future__ import annotations

from dataclasses import dataclass


WORD_SIZE = 4
WORD_MASK = 0xFFFF_FFFF

DEFAULT_INPUT_VECTOR = 0x0000_0004


class InterruptError(Exception):
    """Raised when an invalid interrupt controller operation is performed."""


@dataclass(slots=True)
class InterruptController:
    input_vector_address: int = DEFAULT_INPUT_VECTOR
    input_pending: bool = False
    active: bool = False
    enabled: bool = True

    def __post_init__(self) -> None:
        self.set_input_vector(self.input_vector_address)

    def set_input_vector(self, address: int) -> None:
        if isinstance(address, bool) or not isinstance(address, int):
            raise InterruptError("interrupt vector address must be an integer")

        if not 0 <= address <= WORD_MASK:
            raise InterruptError(
                f"interrupt vector address is out of range: {address}"
            )

        if address != 0 and address % WORD_SIZE != 0:
            raise InterruptError(
                f"interrupt vector address is not aligned: {address:#x}"
            )

        self.input_vector_address = address

    def request_input(self) -> None:
        self.input_pending = True

    def next_handler(self) -> int | None:
        if not self.enabled:
            return None

        if self.active:
            return None
        if not self.input_pending:
            return None
        if self.input_vector_address == 0:
            return None
        self.input_pending = False
        self.active = True
        return self.input_vector_address

    def complete(self) -> None:
        if not self.active:
            raise InterruptError(
                "cannot complete interrupt outside an active interrupt"
            )

        self.active = False

    def enable(self) -> None:
        self.enabled = True

    def disable(self) -> None:
        self.enabled = False

    def reset(self) -> None:
        self.input_pending = False
        self.active = False
        self.enabled = True