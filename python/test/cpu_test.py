import pytest

from main.cpu import CPU, DeviceOverrun, Memory, MemoryFault, Stage
from main.isa import Instruction, Opcode, WORD_MASK, encode
from main.linker import link, to_binary
from main.translator import translate


def image(words: list[int]) -> bytes:
    return b"".join((word & WORD_MASK).to_bytes(4, "little") for word in words)


def load_words(words: list[int]) -> CPU:
    cpu = CPU()
    cpu.load_segments(
        {"text": [(0, image(words))], "rodata": [], "data": [], "bss": []}
    )
    return cpu


def test_end_to_end_assembler_linker_cpu() -> None:
    source = """
    .text
    .global _start
    _start:
        MOVI R1, 65
        STOREB R1, 4(R0)
        HALT
    """
    program = link([translate(source, "smoke.s")])
    cpu = CPU()
    cpu.load_binary(to_binary(program))
    cpu.run(100)

    assert cpu.output_text == "A"
    assert cpu.registers[1] == 65
    assert cpu.halted


def test_reset_vector_and_initial_stack_pointer() -> None:
    cpu = load_words([0x0C, 0, 0, encode(Instruction(Opcode.HALT))])
    assert cpu.pc == 0x0C
    assert cpu.registers[14] == 0x400000
    assert cpu.registers[0] == 0


def test_add_and_zero_register_is_constant() -> None:
    cpu = load_words([
        0x0C, 0, 0,
        encode(Instruction(Opcode.MOVI, rd=1, imm=7)),
        encode(Instruction(Opcode.ADD, rd=0, rs1=1, rs2=1)),
        encode(Instruction(Opcode.ADD, rd=2, rs1=1, rs2=1)),
        encode(Instruction(Opcode.HALT)),
    ])
    cpu.run(100)
    assert cpu.registers[0] == 0
    assert cpu.registers[2] == 14


def test_store_and_load_word_from_data_memory() -> None:
    cpu = load_words([
        0x0C, 0, 0,
        encode(Instruction(Opcode.MOVI, rd=1, imm=123)),
        encode(Instruction(Opcode.STORE, rs1=0, rs2=1, imm=0x2000)),
        encode(Instruction(Opcode.LOAD, rd=2, rs1=0, imm=0x2000)),
        encode(Instruction(Opcode.HALT)),
    ])
    cpu.run(100)
    assert cpu.registers[2] == 123
    assert cpu.memory.read(0x2000, 4) == 123


def test_word_memory_access_takes_ten_cycles() -> None:
    cpu = load_words([
        0x0C, 0, 0,
        encode(Instruction(Opcode.MOVI, rd=1, imm=9)),
        encode(Instruction(Opcode.STORE, rs1=0, rs2=1, imm=0x2000)),
        encode(Instruction(Opcode.HALT)),
    ])
    while cpu.stage is not Stage.MEMORY:
        cpu.tick()
    start = cpu.cycle
    while cpu.stage is Stage.MEMORY:
        cpu.tick()
    assert cpu.cycle - start == 10


def test_mmio_output_write() -> None:
    cpu = load_words([
        0x0C, 0, 0,
        encode(Instruction(Opcode.MOVI, rd=1, imm=ord("X"))),
        encode(Instruction(Opcode.STOREB, rs1=0, rs2=1, imm=4)),
        encode(Instruction(Opcode.HALT)),
    ])
    cpu.run(100)
    assert cpu.output_text == "X"


def test_input_interrupt_reads_and_echoes_one_byte() -> None:
    cpu = load_words([
        0x0C, 0x10, 0,
        encode(Instruction(Opcode.JMP, imm=-4)),  # wait loop at 0x0C
        encode(Instruction(Opcode.LOADB, rd=1, rs1=0, imm=0)),
        encode(Instruction(Opcode.STOREB, rs1=0, rs2=1, imm=4)),
        encode(Instruction(Opcode.IRET)),
    ])
    cpu.schedule_input(3, "Z")
    for _ in range(30):
        cpu.tick()

    assert cpu.output_text == "Z"
    assert cpu.memory.input_byte is None
    assert cpu.in_interrupt is False


def test_input_device_holds_byte_until_read() -> None:
    memory = Memory()
    memory.inject_input(ord("Q"))
    assert memory.read(0, 1) == ord("Q")
    assert memory.input_byte is None


def test_input_overrun_is_not_silently_queued() -> None:
    memory = Memory()
    memory.inject_input(ord("A"))
    with pytest.raises(DeviceOverrun):
        memory.inject_input(ord("B"))


def test_unaligned_word_access_faults() -> None:
    memory = Memory()
    with pytest.raises(MemoryFault, match="unaligned"):
        memory.read(0x2001, 4)


def test_halted_cpu_cannot_tick() -> None:
    cpu = load_words([0x0C, 0, 0, encode(Instruction(Opcode.HALT))])
    cpu.run(20)
    with pytest.raises(Exception, match="halted"):
        cpu.tick()