import pytest
from main.isa import (
    FORMATS,
    REGISTER_INDEX,
    WORD_MASK,
    Format,
    Instruction,
    Opcode,
    decode,
    disassemble,
    encode,
    lower,
    upper,
)

ZERO = REGISTER_INDEX["zero"]
SP = REGISTER_INDEX["sp"]
RA = REGISTER_INDEX["ra"]
R5 = REGISTER_INDEX["r5"]
R6 = REGISTER_INDEX["r6"]
R7 = REGISTER_INDEX["r7"]
R10 = REGISTER_INDEX["r10"]
R11 = REGISTER_INDEX["r11"]

KNOWN_ENCODINGS = [
    (Instruction(Opcode.ADDI, rd=R5, rs1=R5, imm=1), 0x41540001),
    (Instruction(Opcode.ADD, rd=R10, rs1=R10, rs2=R11), 0x06AAC000),
    (Instruction(Opcode.SUB, rd=R5, rs1=R6, rs2=R7), 0x0959C000),
    (Instruction(Opcode.LOAD, rd=R5, rs1=R10, imm=0), 0x51680000),
    (Instruction(Opcode.STORE, rs1=SP, rs2=R5, imm=4), 0x5B940004),
    (Instruction(Opcode.BEQ, rs1=R5, rs2=ZERO, imm=16), 0x81400010),
    (Instruction(Opcode.BEQ, rs1=R5, rs2=ZERO, imm=-4), 0x8143FFFC),
    (Instruction(Opcode.JMP, imm=8), 0xC0000008),
    (Instruction(Opcode.CALL, rd=RA, imm=8), 0xC7C00008),
    (Instruction(Opcode.LUI, rd=R10, imm=0x48D), 0x4A848D00),
    (Instruction(Opcode.ORI, rd=R10, rs1=R10, imm=0x5678), 0x4EA85678),
    (Instruction(Opcode.HALT), 0xD0000000),
]


def sample(opcode: Opcode) -> Instruction:
    match FORMATS[opcode]:
        case Format.REGISTER:
            if opcode in {Opcode.NOP, Opcode.RET, Opcode.IRET, Opcode.HALT}:
                return Instruction(opcode)
            if opcode is Opcode.NOT:
                return Instruction(opcode, rd=R5, rs1=R6)
            return Instruction(opcode, rd=R5, rs1=R6, rs2=R10)
        case Format.IMMEDIATE:
            if opcode is Opcode.MOVI:
                return Instruction(opcode, rd=R5, imm=-7)
            if opcode is Opcode.ORI:
                return Instruction(opcode, rd=R5, rs1=R6, imm=7)
            return Instruction(opcode, rd=R5, rs1=R6, imm=-7)
        case Format.STORE:
            return Instruction(opcode, rs1=SP, rs2=R5, imm=-8)
        case Format.BRANCH:
            return Instruction(opcode, rs1=R6, rs2=R5, imm=-8)
        case Format.UPPER:
            return Instruction(opcode, rd=R5, imm=0x2ABC)
        case Format.JUMP:
            if opcode is Opcode.JMP:
                return Instruction(opcode, imm=-0x100)
            return Instruction(opcode, rd=RA, imm=-0x100)
    raise AssertionError(f"Unhandled opcode: {opcode}")


@pytest.mark.parametrize("opcode", list(Opcode))
def test_roundtrip(opcode: Opcode) -> None:
    instr = sample(opcode)
    assert decode(encode(instr)) == instr


@pytest.mark.parametrize(("instr", "word"), KNOWN_ENCODINGS)
def test_known_machine_encodings(instr: Instruction, word: int) -> None:
    assert encode(instr) == word
    assert decode(word) == instr


def test_register_numbers_and_aliases() -> None:
    assert [REGISTER_INDEX[f"r{i}"] for i in (0, 5, 10, 14, 15)] == [0, 5, 10, 14, 15]
    assert REGISTER_INDEX["zero"] == 0
    assert REGISTER_INDEX["sp"] == 14
    assert REGISTER_INDEX["ra"] == 15
    assert REGISTER_INDEX["x10"] == REGISTER_INDEX["r10"]


@pytest.mark.parametrize(
    "value",
    [0, 0x84, 0x1000, 0x12345678, 0x12345FFF, 0xFFFFFFFF, -1],
)
def test_upper_lower_split(value: int) -> None:
    normalized = value & WORD_MASK
    assert ((upper(value) << 18) | lower(value)) == normalized


def test_split_address_reconstructs_32_bit_value() -> None:
    value = 0x12345678
    upper_part = upper(value)
    lower_part = lower(value)
    assert upper_part == 0x48D
    assert lower_part == 0x5678
    assert ((upper_part << 18) | lower_part) == value


def test_signed_immediate_overflow() -> None:
    with pytest.raises(ValueError, match="does not fit"):
        encode(Instruction(Opcode.ADDI, rd=R5, rs1=R5, imm=1 << 17))


def test_unsigned_ori_immediate_overflow() -> None:
    with pytest.raises(ValueError, match="does not fit"):
        encode(Instruction(Opcode.ORI, rd=R5, rs1=R5, imm=1 << 18))


def test_lui_immediate_overflow() -> None:
    with pytest.raises(ValueError, match="does not fit"):
        encode(Instruction(Opcode.LUI, rd=R5, imm=1 << 14))


def test_branch_offset_must_be_word_aligned() -> None:
    with pytest.raises(ValueError, match="4-byte aligned"):
        encode(Instruction(Opcode.BEQ, rs1=R5, rs2=ZERO, imm=2))


def test_jump_offset_must_be_word_aligned() -> None:
    with pytest.raises(ValueError, match="4-byte aligned"):
        encode(Instruction(Opcode.JMP, imm=6))


def test_reserved_opcode_is_illegal() -> None:
    with pytest.raises(ValueError, match="reserved or unknown opcode"):
        decode(0x30000000)


def test_zero_word_is_nop() -> None:
    assert decode(0) == Instruction(Opcode.NOP)


def test_branch_target_is_relative_to_pc_plus_four() -> None:
    instr = Instruction(Opcode.BEQ, rs1=R5, rs2=ZERO, imm=16)
    assert disassemble(instr, address=0x10) == "beq R5, R0, 0x00000024"


def test_disassemble_memory_instruction() -> None:
    instr = Instruction(Opcode.LOAD, rd=R5, rs1=R10, imm=0)
    assert disassemble(instr, address=0x08) == "load R5, 0(R10)"


def test_disassemble_lui() -> None:
    instr = Instruction(Opcode.LUI, rd=R10, imm=0x48D)
    assert disassemble(instr) == "lui R10, 0x48D"


def test_disassemble_not() -> None:
    instr = Instruction(Opcode.NOT, rd=R5, rs1=R6)
    assert disassemble(instr) == "not R5, R6"


def test_disassemble_halt() -> None:
    assert disassemble(Instruction(Opcode.HALT)) == "halt"


@pytest.mark.parametrize(
    "instruction",
    [
        Instruction(Opcode.NOP),
        Instruction(Opcode.NOT, rd=1, rs1=2),
        Instruction(Opcode.MOVI, rd=3, imm=-(1 << 17)),
        Instruction(Opcode.ADDI, rd=1, rs1=2, imm=(1 << 17) - 1),
        Instruction(Opcode.ORI, rd=1, rs1=2, imm=(1 << 18) - 1),
        Instruction(Opcode.LUI, rd=1, imm=(1 << 14) - 1),
        Instruction(Opcode.LOADB, rd=1, rs1=2, imm=-16),
        Instruction(Opcode.STOREB, rs1=2, rs2=3, imm=16),
        Instruction(Opcode.BNE, rs1=1, rs2=2, imm=-(1 << 17)),
        Instruction(Opcode.BGE, rs1=1, rs2=2, imm=(1 << 17) - 4),
        Instruction(Opcode.JMP, imm=-(1 << 21)),
        Instruction(Opcode.CALL, rd=15, imm=(1 << 21) - 4),
        Instruction(Opcode.RET),
        Instruction(Opcode.IRET),
        Instruction(Opcode.HALT),
    ],
)
def test_additional_encode_decode_boundaries(instruction: Instruction) -> None:
    assert decode(encode(instruction)) == instruction


@pytest.mark.parametrize("value", [-(1 << 17) - 1, 1 << 17])
def test_signed_immediate_rejects_both_overflow_directions(value: int) -> None:
    with pytest.raises(ValueError):
        encode(Instruction(Opcode.ADDI, rd=1, rs1=2, imm=value))


@pytest.mark.parametrize("value", [-1, 1 << 18])
def test_ori_rejects_both_unsigned_overflow_directions(value: int) -> None:
    with pytest.raises(ValueError):
        encode(Instruction(Opcode.ORI, rd=1, rs1=2, imm=value))


@pytest.mark.parametrize("value", [-(1 << 21) - 4, 1 << 21])
def test_jump_rejects_displacement_overflow(value: int) -> None:
    with pytest.raises(ValueError):
        encode(Instruction(Opcode.JMP, imm=value))


def test_decode_rejects_nonzero_reserved_bits_for_register_instruction() -> None:
    word = encode(Instruction(Opcode.ADD, rd=1, rs1=2, rs2=3))
    with pytest.raises(ValueError, match="reserved bits"):
        decode(word | 0x1)


def test_decode_rejects_nonzero_reserved_bits_for_lui() -> None:
    word = encode(Instruction(Opcode.LUI, rd=1, imm=0x123))
    with pytest.raises(ValueError, match="reserved bits"):
        decode(word | 0x1)


@pytest.mark.parametrize(
    "instruction",
    [
        Instruction(Opcode.NOP, rd=1),
        Instruction(Opcode.RET, rs1=1),
        Instruction(Opcode.IRET, rs2=1),
        Instruction(Opcode.HALT, imm=1),
        Instruction(Opcode.MOVI, rd=1, rs1=2, imm=1),
        Instruction(Opcode.LUI, rd=1, rs2=2, imm=1),
        Instruction(Opcode.JMP, rd=1, imm=4),
    ],
)
def test_encoder_rejects_forbidden_operands(instruction: Instruction) -> None:
    with pytest.raises(ValueError):
        encode(instruction)


def test_branch_target_wraps_to_32_bits() -> None:
    from main.isa import branch_target

    instruction = Instruction(Opcode.JMP, imm=4)
    assert branch_target(0xFFFF_FFFC, instruction) == 4


def test_instruction_byte_order_is_little_endian() -> None:
    from main.isa import instruction_from_bytes, instruction_to_bytes

    instruction = Instruction(Opcode.ADDI, rd=1, rs1=2, imm=1)
    raw = instruction_to_bytes(instruction)
    assert raw == encode(instruction).to_bytes(4, byteorder="little")
    assert instruction_from_bytes(raw) == instruction


def test_instruction_from_bytes_rejects_wrong_size() -> None:
    from main.isa import instruction_from_bytes

    with pytest.raises(ValueError, match="exactly 4 bytes"):
        instruction_from_bytes(b"\x00\x00\x00")


def test_iter_instructions_reports_sequential_addresses() -> None:
    from main.isa import instruction_to_bytes, iter_instructions

    first = Instruction(Opcode.NOP)
    second = Instruction(Opcode.HALT)
    image = instruction_to_bytes(first) + instruction_to_bytes(second)
    assert list(iter_instructions(image, start_address=0x100)) == [
        (0x100, first),
        (0x104, second),
    ]


def test_iter_instructions_rejects_partial_instruction() -> None:
    from main.isa import iter_instructions

    with pytest.raises(ValueError, match="multiple of 4"):
        list(iter_instructions(b"\x00\x00\x00"))
