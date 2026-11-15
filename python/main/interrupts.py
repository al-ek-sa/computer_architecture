from __future__ import annotations

from dataclasses import dataclass


class InterruptError(RuntimeError):
    """Invalid interrupt-controller operation."""


@dataclass(slots=True)
class InterruptController:
    input_vector_address: int = 0
    input_pending: bool = False
    active: bool = False
    enabled: bool = True

    def request_input(self) -> None:
        self.input_pending = True

    def next_handler(self) -> int | None:
        if not self.enabled or self.active or not self.input_pending:
            return None
        if self.input_vector_address == 0:
            return None
        self.input_pending = False
        self.active = True
        return self.input_vector_address

    def complete(self) -> None:
        if not self.active:
            raise InterruptError("IRET outside an active interrupt")
        self.active = False

    def reset(self) -> None:
        self.input_pending = False
        self.active = False