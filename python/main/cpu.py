from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Iterable

try:
    from .isa import (
        CYCLE_COUNTER,
        DMEM_SIZE,
        IMEM_SIZE,
        INITIAL_SP,
        INPUT_DATA,
        INPUT_STATUS,
        INPUT_VECTOR,
        MMIO_END,
        OUTPUT_DATA,
        RA_REGISTER,
        RESET_VECTOR,
        SP_REGISTER,
        WORD_MASK,
        WORD_SIZE,
        Instruction,
        Opcode,
        branch_target,
        decode,
    )
    from .linker import LinkError, from_binary
except ImportError:
    from isa import (
        CYCLE_COUNTER,
        DMEM_SIZE,
        IMEM_SIZE,
        INITIAL_SP,
        INPUT_DATA,
        INPUT_STATUS,
        INPUT_VECTOR,
        MMIO_END,
        OUTPUT_DATA,
        RA_REGISTER,
        RESET_VECTOR,
        SP_REGISTER,
        WORD_MASK,
        WORD_SIZE,
        Instruction,
        Opcode,
        branch_target,
        decode,
    )
    from linker import LinkError, from_binary
    from linker import LinkError, from_binary


class CPUError(RuntimeError):
    """Processor execution error."""


class MemoryFault(CPUError):
    """Invalid memory access."""


class DeviceOverrun(CPUError):
    """Input arrived while the one-byte device holding register was occupied."""


class Stage(Enum):
    FETCH = auto()
    DECODE = auto()
    EXECUTE = auto()
    MEMORY = auto()
    WRITEBACK = auto()
    HALTED = auto()


@dataclass(frozen=True, slots=True)
class InputEvent:
    cycle: int
    data: bytes


@dataclass(frozen=True, slots=True)
class TraceEntry:
    cycle: int
    stage: str
    pc: int
    instruction: str
    registers: tuple[int, ...]
    detail: str = ""


@dataclass(slots=True)
class Memory:
    instruction: bytearray = field(default_factory=lambda: bytearray(IMEM_SIZE))
    data: bytearray = field(default_factory=lambda: bytearray(DMEM_SIZE))
    input_byte: int | None = None
    output: bytearray = field(default_factory=bytearray)
    cycle_counter: int = 0

    def load_segments(self, segments: dict[str, list[tuple[int, bytes]]]) -> None:
        for section, items in segments.items():
            target = self.instruction if section == "text" else self.data
            limit = IMEM_SIZE if section == "text" else DMEM_SIZE
            for address, payload in items:
                end = address + len(payload)
                if address < 0 or end > limit:
                    raise MemoryFault(
                        f"{section} segment [{address:#x}, {end:#x}) is out of range"
                    )
                if section != "text" and address < MMIO_END:
                    raise MemoryFault("program data may not overwrite MMIO registers")
                target[address:end] = payload

    def fetch_word(self, address: int) -> int:
        if address % WORD_SIZE:
            raise MemoryFault(f"unaligned instruction address: {address:#x}")
        if address < 0 or address + WORD_SIZE > IMEM_SIZE:
            raise MemoryFault(f"instruction address out of range: {address:#x}")
        return int.from_bytes(self.instruction[address:address + WORD_SIZE], "little")

    def read(self, address: int, size: int) -> int:
        if size not in (1, WORD_SIZE):
            raise MemoryFault(f"unsupported read size: {size}")
        if address < 0 or address + size > DMEM_SIZE:
            raise MemoryFault(f"data address out of range: {address:#x}")
        if size == WORD_SIZE and address % WORD_SIZE:
            raise MemoryFault(f"unaligned word read: {address:#x}")

        if address < MMIO_END:
            if size == WORD_SIZE and address % WORD_SIZE:
                raise MemoryFault(f"unaligned MMIO word read: {address:#x}")
            if address == INPUT_DATA:
                if self.input_byte is None:
                    return 0
                value = self.input_byte
                self.input_byte = None
                return value
            if address == OUTPUT_DATA:
                return 0
            if address == CYCLE_COUNTER:
                return self.cycle_counter & WORD_MASK
            if address == INPUT_STATUS:
                return int(self.input_byte is not None)
            raise MemoryFault(f"unmapped MMIO read: {address:#x}")

        return int.from_bytes(self.data[address:address + size], "little")

    def write(self, address: int, value: int, size: int) -> None:
        if size not in (1, WORD_SIZE):
            raise MemoryFault(f"unsupported write size: {size}")
        if address < 0 or address + size > DMEM_SIZE:
            raise MemoryFault(f"data address out of range: {address:#x}")
        if size == WORD_SIZE and address % WORD_SIZE:
            raise MemoryFault(f"unaligned word write: {address:#x}")
        value &= (1 << (size * 8)) - 1

        if address < MMIO_END:
            if address == OUTPUT_DATA:
                self.output.append(value & 0xFF)
                return
            if address in (INPUT_DATA, CYCLE_COUNTER, INPUT_STATUS):
                raise MemoryFault(f"MMIO register is read-only: {address:#x}")
            raise MemoryFault(f"unmapped MMIO write: {address:#x}")

        self.data[address:address + size] = value.to_bytes(size, "little")

    def inject_input(self, value: int) -> None:
        if self.input_byte is not None:
            raise DeviceOverrun(
                f"input overrun at cycle {self.cycle_counter}: "
                f"unread byte {self.input_byte:#04x}"
            )
        self.input_byte = value & 0xFF

    def consume_input(self) -> int:
        if self.input_byte is None:
            return 0
        value = self.input_byte
        self.input_byte = None
        return value


@dataclass(slots=True)
class CPU:
    memory: Memory = field(default_factory=Memory)
    registers: list[int] = field(default_factory=lambda: [0] * 16)
    pc: int = 0
    ir: int = 0
    epc: int = 0
    stage: Stage = Stage.FETCH
    cycle: int = 0
    halted: bool = False
    in_interrupt: bool = False
    pending_interrupt: bool = False
    input_schedule: list[InputEvent] = field(default_factory=list)
    trace: list[TraceEntry] = field(default_factory=list)
    _instruction: Instruction | None = None
    _operands: tuple[int, int] = (0, 0)
    _result: int | None = None
    _memory_address: int = 0
    _memory_value: int = 0
    _memory_size: int = WORD_SIZE
    _memory_is_load: bool = False
    _memory_wait: int = 0
    _next_pc: int | None = None
    _detail: str = ""

    def reset(self) -> None:
        self.registers[:] = [0] * 16
        self.registers[SP_REGISTER] = INITIAL_SP
        self.pc = self.memory.fetch_word(RESET_VECTOR)
        self.ir = 0
        self.epc = 0
        self.stage = Stage.FETCH
        self.cycle = 0
        self.halted = False
        self.in_interrupt = False
        self.pending_interrupt = False
        self.trace.clear()
        self._clear_pipeline()
        self.memory.cycle_counter = 0

    def load_binary(self, binary: bytes, *, reset: bool = True) -> None:
        try:
            segments = from_binary(binary)
        except LinkError as error:
            raise CPUError(f"cannot load executable: {error}") from None
        self.memory = Memory()
        self.memory.load_segments(segments)
        if reset:
            self.reset()

    def load_file(self, path: str | Path, *, reset: bool = True) -> None:
        try:
            binary = Path(path).read_bytes()
        except OSError as error:
            raise CPUError(f"cannot read executable {path}: {error}") from None
        self.load_binary(binary, reset=reset)

    def load_segments(
        self, segments: dict[str, list[tuple[int, bytes]]], *, reset: bool = True
    ) -> None:
        self.memory = Memory()
        self.memory.load_segments(segments)
        if reset:
            self.reset()

    def schedule_input(self, cycle: int, data: bytes | str) -> None:
        if cycle < 1:
            raise ValueError("input event cycle must be >= 1")
        payload = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        if not payload:
            return

        for offset, byte in enumerate(payload):
            self.input_schedule.append(InputEvent(cycle + offset, bytes((byte,))))
        self.input_schedule.sort(key=lambda event: event.cycle)

    def _clear_pipeline(self) -> None:
        self._instruction = None
        self._operands = (0, 0)
        self._result = None
        self._memory_address = 0
        self._memory_value = 0
        self._memory_size = WORD_SIZE
        self._memory_is_load = False
        self._memory_wait = 0
        self._next_pc = None
        self._detail = ""

    def _deliver_scheduled_input(self) -> None:
        due = [event for event in self.input_schedule if event.cycle == self.cycle]
        if not due:
            return
        self.input_schedule = [
            event for event in self.input_schedule if event.cycle != self.cycle
        ]
        for event in due:
            for byte in event.data:
                self.memory.inject_input(byte)
                self.pending_interrupt = True

    def _take_interrupt(self) -> None:
        self.epc = self.pc
        self.pc = self.memory.fetch_word(INPUT_VECTOR)
        self.in_interrupt = True
        self.pending_interrupt = False
        self._detail = f"input interrupt: EPC={self.epc:#010x}, vector={self.pc:#010x}"

    def _signed(self, value: int) -> int:
        value &= WORD_MASK
        return value - (1 << 32) if value & 0x8000_0000 else value

    def _write_register(self, index: int, value: int) -> None:
        if index != 0:
            self.registers[index] = value & WORD_MASK
        self.registers[0] = 0

    def tick(self) -> TraceEntry:
        if self.halted:
            raise CPUError("cannot tick a halted processor")

        self.cycle += 1
        self.memory.cycle_counter = self.cycle
        self._deliver_scheduled_input()
        self._detail = ""
        instruction_name = (
            self._instruction.opcode.mnemonic if self._instruction is not None else ""
        )

        if self.stage is Stage.FETCH:
            if self.pending_interrupt and not self.in_interrupt:
                input_handler = self.memory.fetch_word(INPUT_VECTOR)
                if input_handler != 0:
                    self._take_interrupt()
            self.ir = self.memory.fetch_word(self.pc)
            self.stage = Stage.DECODE

        elif self.stage is Stage.DECODE:
            try:
                self._instruction = decode(self.ir)
            except ValueError as error:
                raise CPUError(f"invalid instruction at {self.pc:#010x}: {error}") from None
            instr = self._instruction
            self._operands = (self.registers[instr.rs1], self.registers[instr.rs2])
            self._next_pc = (self.pc + WORD_SIZE) & WORD_MASK
            self.stage = Stage.EXECUTE
            self._detail = instr.opcode.mnemonic

        elif self.stage is Stage.EXECUTE:
            self._execute()

        elif self.stage is Stage.MEMORY:
            if self._memory_wait > 1:
                self._memory_wait -= 1
                self._detail = f"memory wait ({self._memory_wait} cycles remain)"
            else:
                self._memory_wait = 0
                if self._memory_is_load:
                    self._result = self.memory.read(
                        self._memory_address, self._memory_size
                    )
                    self.stage = Stage.WRITEBACK
                    self._detail = f"load {self._memory_address:#010x}"
                else:
                    self.memory.write(
                        self._memory_address,
                        self._memory_value,
                        self._memory_size,
                    )
                    self.pc = self._next_pc if self._next_pc is not None else self.pc
                    self.stage = Stage.FETCH
                    self._detail = f"store {self._memory_address:#010x}"
                    self._clear_pipeline()

        elif self.stage is Stage.WRITEBACK:
            instr = self._require_instruction()
            if self._result is not None:
                self._write_register(instr.rd, self._result)
            self.pc = self._next_pc if self._next_pc is not None else self.pc
            self.stage = Stage.FETCH
            self._detail = f"writeback {instr.opcode.mnemonic}"
            self._clear_pipeline()

        entry = TraceEntry(
            cycle=self.cycle,
            stage=self.stage.name,
            pc=self.pc,
            instruction=instruction_name or (
                self._instruction.opcode.mnemonic if self._instruction else ""
            ),
            registers=tuple(self.registers),
            detail=self._detail,
        )
        self.trace.append(entry)
        return entry

    def _require_instruction(self) -> Instruction:
        if self._instruction is None:
            raise CPUError("internal error: no decoded instruction")
        return self._instruction

    def _execute(self) -> None:
        instr = self._require_instruction()
        op = instr.opcode
        a, b = self._operands
        self._result = None

        if op is Opcode.NOP:
            pass
        elif op is Opcode.ADD:
            self._result = a + b
        elif op is Opcode.SUB:
            self._result = a - b
        elif op is Opcode.MUL:
            self._result = a * b
        elif op is Opcode.DIV:
            if b == 0:
                raise CPUError(f"division by zero at PC={self.pc:#010x}")
            quotient = abs(self._signed(a)) // abs(self._signed(b))
            if (self._signed(a) < 0) != (self._signed(b) < 0):
                quotient = -quotient
            self._result = quotient
        elif op is Opcode.AND:
            self._result = a & b
        elif op is Opcode.OR:
            self._result = a | b
        elif op is Opcode.XOR:
            self._result = a ^ b
        elif op is Opcode.NOT:
            self._result = ~a
        elif op is Opcode.SHL:
            self._result = a << (b & 0x1F)
        elif op is Opcode.SHR:
            self._result = a >> (b & 0x1F)
        elif op is Opcode.ADDI:
            self._result = a + instr.imm
        elif op is Opcode.MOVI:
            self._result = instr.imm
        elif op is Opcode.LUI:
            self._result = instr.imm << 18
        elif op is Opcode.ORI:
            self._result = a | instr.imm
        elif op in (Opcode.LOAD, Opcode.LOADB):
            self._memory_address = (a + instr.imm) & WORD_MASK
            self._memory_size = 1 if op is Opcode.LOADB else WORD_SIZE
            self._memory_is_load = True
            self._memory_wait = 1 if self._memory_address < MMIO_END else 10
            self.stage = Stage.MEMORY
            self._detail = f"load request {self._memory_address:#010x}"
            return
        elif op in (Opcode.STORE, Opcode.STOREB):
            self._memory_address = (a + instr.imm) & WORD_MASK
            self._memory_value = b
            self._memory_size = 1 if op is Opcode.STOREB else WORD_SIZE
            self._memory_is_load = False
            self._memory_wait = 1 if self._memory_address < MMIO_END else 10
            self.stage = Stage.MEMORY
            self._detail = f"store request {self._memory_address:#010x}"
            return
        elif op in (Opcode.BEQ, Opcode.BNE, Opcode.BLT, Opcode.BGE):
            if op is Opcode.BEQ:
                take = a == b
            elif op is Opcode.BNE:
                take = a != b
            elif op is Opcode.BLT:
                take = self._signed(a) < self._signed(b)
            else:
                take = self._signed(a) >= self._signed(b)
            if take:
                self._next_pc = branch_target(self.pc, instr)
        elif op is Opcode.SLT:
            self._result = int(self._signed(a) < self._signed(b))
        elif op is Opcode.SLTU:
            self._result = int(a < b)
        elif op is Opcode.JMP:
            self._next_pc = branch_target(self.pc, instr)
        elif op is Opcode.CALL:
            self._result = (self.pc + WORD_SIZE) & WORD_MASK
            self._next_pc = branch_target(self.pc, instr)
        elif op is Opcode.RET:
            self._next_pc = self.registers[RA_REGISTER]
        elif op is Opcode.IRET:
            if not self.in_interrupt:
                raise CPUError(f"IRET outside interrupt handler at PC={self.pc:#010x}")
            self._next_pc = self.epc
            self.in_interrupt = False
        elif op is Opcode.HALT:
            self.halted = True
            self.stage = Stage.HALTED
            self._detail = "halt"
            return
        else:
            raise CPUError(f"unimplemented opcode: {op}")

        if self._result is not None:
            self.stage = Stage.WRITEBACK
        else:
            self.pc = self._next_pc if self._next_pc is not None else self.pc
            self.stage = Stage.FETCH
            self._clear_pipeline()

    def run(self, max_cycles: int = 100_000) -> list[TraceEntry]:
        if max_cycles < 1:
            raise ValueError("max_cycles must be positive")
        while not self.halted and self.cycle < max_cycles:
            self.tick()
        if not self.halted:
            raise CPUError(f"cycle limit exceeded ({max_cycles})")
        return self.trace

    @property
    def output_text(self) -> str:
        return self.memory.output.decode("utf-8", errors="replace")

    def dump_registers(self) -> str:
        return "\n".join(
            f"R{index:02d} = 0x{value:08X}"
            for index, value in enumerate(self.registers)
        ) + f"\nPC  = 0x{self.pc:08X}\nEPC = 0x{self.epc:08X}\n"