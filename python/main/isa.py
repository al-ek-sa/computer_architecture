from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

WORD_SIZE = 4
WORD_BITS = 32
WORD_MASK = 0xFFFF_FFFF

IMEM_SIZE = 0x1_0000
DMEM_SIZE = 0x40_0000

RESET_VECTOR = 0x0000
INPUT_VECTOR = 0x0004
RESERVED_VECTOR = 0x0008
TEXT_START = 0x000C

MMIO_START = 0x0000_0000
INPUT_DATA = 0x0000_0000
OUTPUT_DATA = 0x0000_0004
CYCLE_COUNTER = 0x0000_0008
INPUT_STATUS = 0x0000_000C
MMIO_END = 0x0000_0010

RESERVED_START = 0x0000_0010
RODATA_START = 0x0000_1000
RODATA_END = 0x0000_2000
DATA_START = 0x0000_2000
DATA_END = 0x0000_3000
BSS_START = 0x0000_3000
BSS_END = 0x0000_4000
HEAP_START = 0x0000_4000
HEAP_END = 0x0030_0000
STACK_BASE = 0x0030_0000
STACK_TOP = DMEM_SIZE
INITIAL_SP = STACK_TOP

REGISTER_COUNT = 16
ZERO_REGISTER = 0
SP_REGISTER = 14
RA_REGISTER = 15
REGISTERS = tuple(f"R{i}" for i in range(REGISTER_COUNT))
REGISTER_INDEX = {
    **{name.lower(): index for index, name in enumerate(REGISTERS)},
    **{f"x{index}": index for index in range(REGISTER_COUNT)},
}
REGISTER_INDEX.update({"zero": 0, "sp": 14, "ra": 15})

class Opcode(Enum):
    NOP = 0x00
    ADD = 0x01
    SUB = 0x02
    MUL = 0x03
    DIV = 0x04
    AND = 0x05
    OR = 0x06
    XOR = 0x07
    NOT = 0x08
    SHL = 0x09
    SHR = 0x0A

    ADDI = 0x10
    MOVI = 0x11
    LUI = 0x12
    ORI = 0x13
    LOAD = 0x14
    LOADB = 0x15
    STORE = 0x16
    STOREB = 0x17

    BEQ = 0x20
    BNE = 0x21
    BLT = 0x22
    BGE = 0x23
    SLT = 0x24
    SLTU = 0x25

    JMP = 0x30
    CALL = 0x31
    RET = 0x32
    IRET = 0x33
    HALT = 0x34

    @property
    def mnemonic(self) -> str:
        return self.name.lower()


class Format(Enum):
    REGISTER = "R"
    IMMEDIATE = "I"
    STORE = "S"
    BRANCH = "B"
    JUMP = "J"
    UPPER = "U"


FORMATS: dict[Opcode, Format] = {
    Opcode.NOP: Format.REGISTER,
    Opcode.ADD: Format.REGISTER,
    Opcode.SUB: Format.REGISTER,
    Opcode.MUL: Format.REGISTER,
    Opcode.DIV: Format.REGISTER,
    Opcode.AND: Format.REGISTER,
    Opcode.OR: Format.REGISTER,
    Opcode.XOR: Format.REGISTER,
    Opcode.NOT: Format.REGISTER,
    Opcode.SHL: Format.REGISTER,
    Opcode.SHR: Format.REGISTER,
    Opcode.ADDI: Format.IMMEDIATE,
    Opcode.MOVI: Format.IMMEDIATE,
    Opcode.LUI: Format.UPPER,
    Opcode.ORI: Format.IMMEDIATE,
    Opcode.LOAD: Format.IMMEDIATE,
    Opcode.LOADB: Format.IMMEDIATE,
    Opcode.STORE: Format.STORE,
    Opcode.STOREB: Format.STORE,
    Opcode.BEQ: Format.BRANCH,
    Opcode.BNE: Format.BRANCH,
    Opcode.BLT: Format.BRANCH,
    Opcode.BGE: Format.BRANCH,
    Opcode.SLT: Format.REGISTER,
    Opcode.SLTU: Format.REGISTER,
    Opcode.JMP: Format.JUMP,
    Opcode.CALL: Format.JUMP,
    Opcode.RET: Format.REGISTER,
    Opcode.IRET: Format.REGISTER,
    Opcode.HALT: Format.REGISTER,
}

OPCODES = {opcode.value: opcode for opcode in Opcode}
MNEMONICS = {opcode.mnemonic: opcode for opcode in Opcode}
LOADS = frozenset({Opcode.LOAD, Opcode.LOADB})
STORES = frozenset({Opcode.STORE, Opcode.STOREB})

SIGNED_IMMEDIATE_BITS = 18
UNSIGNED_IMMEDIATE_BITS = 18
BRANCH_DISPLACEMENT_BITS = 18
JUMP_DISPLACEMENT_BITS = 22
UPPER_IMMEDIATE_BITS = 14


class ISAError(ValueError):
    """Invalid instruction or instruction encoding."""


@dataclass(frozen=True, slots=True)
class Instruction:
    opcode: Opcode
    rd: int = 0
    rs1: int = 0
    rs2: int = 0
    imm: int = 0

    def __post_init__(self) -> None:
        for field_name, register in (
            ("rd", self.rd),
            ("rs1", self.rs1),
            ("rs2", self.rs2),
        ):
            if not 0 <= register < REGISTER_COUNT:
                raise ISAError(f"{field_name} register out of range: {register}")


def _check_unsigned(value: int, width: int, what: str) -> int:
    if not 0 <= value < (1 << width):
        raise ISAError(f"{what} {value} does not fit into {width} unsigned bits")
    return value


def _check_signed(value: int, width: int, what: str) -> int:
    limit = 1 << (width - 1)
    if not -limit <= value < limit:
        raise ISAError(f"{what} {value} does not fit into {width} signed bits")
    return value & ((1 << width) - 1)


def _sign_extend(value: int, width: int) -> int:
    sign = 1 << (width - 1)
    return (value ^ sign) - sign


def _check_displacement(value: int, width: int) -> int:
    if value % WORD_SIZE:
        raise ISAError(
            f"PC-relative displacement must be {WORD_SIZE}-byte aligned: {value}"
        )
    return _check_signed(value, width, "displacement")


def _validate_unused(instr: Instruction) -> None:
    op = instr.opcode
    if op == Opcode.NOP or op in {Opcode.RET, Opcode.IRET, Opcode.HALT}:
        if instr.rd or instr.rs1 or instr.rs2 or instr.imm:
            raise ISAError(f"{op.mnemonic} does not take operands")
    elif op == Opcode.MOVI:
        if instr.rs1 or instr.rs2:
            raise ISAError("movi uses only rd and immediate")
    elif op == Opcode.LUI:
        if instr.rs1 or instr.rs2:
            raise ISAError("lui uses only rd and immediate")
    elif op in {Opcode.JMP, Opcode.CALL}:
        if op == Opcode.JMP and instr.rd:
            raise ISAError("jmp has no destination register; rd must be R0")


def encode(instr: Instruction) -> int:
    _validate_unused(instr)
    op = instr.opcode.value
    fmt = FORMATS[instr.opcode]
    word = op << 26

    if fmt is Format.REGISTER:
        word |= instr.rd << 22
        word |= instr.rs1 << 18
        word |= instr.rs2 << 14

    elif fmt is Format.IMMEDIATE:
        if instr.opcode == Opcode.ORI:
            immediate = _check_unsigned(
                instr.imm, UNSIGNED_IMMEDIATE_BITS, "ORI immediate"
            )
        else:
            immediate = _check_signed(
                instr.imm, SIGNED_IMMEDIATE_BITS, "immediate"
            )
        word |= instr.rd << 22
        word |= instr.rs1 << 18
        word |= immediate

    elif fmt is Format.STORE:
        offset = _check_signed(instr.imm, SIGNED_IMMEDIATE_BITS, "store offset")
        word |= instr.rs1 << 22
        word |= instr.rs2 << 18
        word |= offset

    elif fmt is Format.BRANCH:
        displacement = _check_displacement(
            instr.imm, BRANCH_DISPLACEMENT_BITS
        )
        word |= instr.rs1 << 22
        word |= instr.rs2 << 18
        word |= displacement

    elif fmt is Format.JUMP:
        displacement = _check_displacement(
            instr.imm, JUMP_DISPLACEMENT_BITS
        )
        word |= instr.rd << 22
        word |= displacement

    elif fmt is Format.UPPER:
        immediate = _check_unsigned(
            instr.imm, UPPER_IMMEDIATE_BITS, "LUI immediate"
        )
        word |= instr.rd << 22
        word |= immediate << 8

    else:
        raise ISAError(f"unsupported instruction format: {fmt}")

    return word & WORD_MASK


def decode(word: int) -> Instruction:
    if not 0 <= word <= WORD_MASK:
        raise ISAError(f"instruction word out of range: {word}")

    opcode_value = (word >> 26) & 0x3F
    try:
        opcode = Opcode(opcode_value)
    except ValueError:
        raise ISAError(f"reserved or unknown opcode: 0x{opcode_value:02X}") from None

    fmt = FORMATS[opcode]
    rd = (word >> 22) & 0xF
    rs1 = (word >> 18) & 0xF
    rs2 = (word >> 14) & 0xF
    imm18 = _sign_extend(word & 0x3FFFF, 18)

    if fmt is Format.REGISTER:
        if word & 0x3FFF:
            raise ISAError(f"nonzero reserved bits in {opcode.mnemonic}")
        instr = Instruction(opcode, rd=rd, rs1=rs1, rs2=rs2)

    elif fmt is Format.IMMEDIATE:
        raw_imm = word & 0x3FFFF
        immediate = raw_imm if opcode == Opcode.ORI else _sign_extend(raw_imm, 18)
        instr = Instruction(opcode, rd=rd, rs1=rs1, imm=immediate)

    elif fmt is Format.STORE:
        instr = Instruction(
            opcode, rs1=rd, rs2=rs1, imm=imm18
        )

    elif fmt is Format.BRANCH:
        instr = Instruction(
            opcode, rs1=rd, rs2=rs1, imm=imm18
        )
        if instr.imm % WORD_SIZE:
            raise ISAError("branch displacement is not word-aligned")

    elif fmt is Format.JUMP:
        raw = word & 0x3F_FFFF
        displacement = _sign_extend(raw, JUMP_DISPLACEMENT_BITS)
        instr = Instruction(opcode, rd=rd, imm=displacement)
        if displacement % WORD_SIZE:
            raise ISAError("jump displacement is not word-aligned")

    elif fmt is Format.UPPER:
        if word & 0xFF:
            raise ISAError("nonzero reserved bits in LUI")
        instr = Instruction(opcode, rd=rd, imm=(word >> 8) & 0x3FFF)

    else:
        raise ISAError(f"unsupported instruction format: {fmt}")

    _validate_unused(instr)
    return instr


def branch_target(pc: int, instr: Instruction) -> int:
    if FORMATS[instr.opcode] not in {Format.BRANCH, Format.JUMP}:
        raise ISAError("instruction is not PC-relative")
    return (pc + WORD_SIZE + instr.imm) & WORD_MASK


def upper(value: int) -> int:
    return (value & WORD_MASK) >> 18


def lower(value: int) -> int:
    return value & 0x3_FFFF


def split_address(value: int) -> tuple[int, int]:
    if not 0 <= value <= WORD_MASK:
        raise ISAError(f"32-bit value out of range: {value}")
    return upper(value), lower(value)


def disassemble(instr: Instruction, address: int = 0) -> str:
    op = instr.opcode
    rd, rs1, rs2 = REGISTERS[instr.rd], REGISTERS[instr.rs1], REGISTERS[instr.rs2]

    if op in {Opcode.NOP, Opcode.RET, Opcode.IRET, Opcode.HALT}:
        operands = ""
    elif op in {Opcode.ADD, Opcode.SUB, Opcode.MUL, Opcode.DIV,
                Opcode.AND, Opcode.OR, Opcode.XOR, Opcode.SHL, Opcode.SHR,
                Opcode.SLT, Opcode.SLTU}:
        if op == Opcode.NOT:
            operands = f"{rd}, {rs1}"
        else:
            operands = f"{rd}, {rs1}, {rs2}"
    elif op == Opcode.NOT:
        operands = f"{rd}, {rs1}"
    elif op == Opcode.MOVI:
        operands = f"{rd}, {instr.imm}"
    elif op == Opcode.LUI:
        operands = f"{rd}, 0x{instr.imm:X}"
    elif op in {Opcode.ADDI, Opcode.ORI}:
        operands = f"{rd}, {rs1}, {instr.imm}"
    elif op in {Opcode.LOAD, Opcode.LOADB}:
        operands = f"{rd}, {instr.imm}({rs1})"
    elif op in {Opcode.STORE, Opcode.STOREB}:
        operands = f"{rs2}, {instr.imm}({rs1})"
    elif op in {Opcode.BEQ, Opcode.BNE, Opcode.BLT, Opcode.BGE}:
        target = branch_target(address, instr)
        operands = f"{rs1}, {rs2}, 0x{target:08X}"
    elif op == Opcode.JMP:
        target = branch_target(address, instr)
        operands = f"0x{target:08X}"
    elif op == Opcode.CALL:
        target = branch_target(address, instr)
        operands = f"{rd}, 0x{target:08X}"
    else:
        raise ISAError(f"cannot disassemble {op}")

    return f"{op.mnemonic} {operands}".rstrip()


def instruction_to_bytes(instr: Instruction) -> bytes:
    return encode(instr).to_bytes(WORD_SIZE, "little")


def instruction_from_bytes(data: bytes) -> Instruction:
    if len(data) != WORD_SIZE:
        raise ISAError(f"instruction must be exactly {WORD_SIZE} bytes")
    return decode(int.from_bytes(data, "little"))


def iter_instructions(data: bytes, start_address: int = 0):
    if len(data) % WORD_SIZE:
        raise ISAError("instruction memory image size is not a multiple of 4")
    for offset in range(0, len(data), WORD_SIZE):
        word = int.from_bytes(data[offset:offset + WORD_SIZE], "little")
        yield start_address + offset, decode(word)