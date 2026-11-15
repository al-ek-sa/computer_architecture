import pytest

from main.memory import HarvardMemory, InstructionMemory, MemoryFault, SparseDataMemory


def test_instruction_memory_load_and_fetch_little_endian():
    memory = InstructionMemory(size=64)
    memory.load(4, bytes.fromhex("78563412"))
    assert memory.fetch_word(4) == 0x12345678
    assert memory.read(4, 4) == bytes.fromhex("78563412")


def test_instruction_memory_rejects_unaligned_fetch():
    memory = InstructionMemory(size=64)
    with pytest.raises(MemoryFault, match="unaligned"):
        memory.fetch_word(2)


def test_instruction_memory_rejects_out_of_range_segment():
    memory = InstructionMemory(size=16)
    with pytest.raises(MemoryFault):
        memory.load(15, b"ab")


def test_sparse_data_memory_reads_unallocated_bytes_as_zero():
    memory = SparseDataMemory()
    assert memory.read(0x123450, 4) == 0
    assert memory.allocated_pages() == 0


def test_sparse_data_memory_round_trip_and_little_endian():
    memory = SparseDataMemory()
    memory.write(0x2000, 0x12345678, 4)
    assert memory.read(0x2000, 4) == 0x12345678
    assert memory.read_bytes(0x2000, 4) == bytes.fromhex("78563412")


def test_sparse_data_memory_supports_high_32_bit_addresses():
    memory = SparseDataMemory()
    address = 0xFFFF_FFF0
    memory.write(address, 0xAABBCCDD, 4)
    assert memory.read(address, 4) == 0xAABBCCDD


def test_sparse_data_memory_access_crosses_page_boundary():
    memory = SparseDataMemory(page_bits=4)
    memory.write_bytes(14, b"abcd")
    assert memory.read_bytes(14, 4) == b"abcd"
    assert memory.allocated_pages() == 2


@pytest.mark.parametrize("address,size", [(-1, 1), (0x1_0000_0000, 1), (0xFFFF_FFFF, 2)])
def test_sparse_data_memory_rejects_invalid_ranges(address, size):
    memory = SparseDataMemory()
    with pytest.raises(MemoryFault):
        memory.read_bytes(address, size)


def test_sparse_data_memory_rejects_unsupported_width():
    memory = SparseDataMemory()
    with pytest.raises(MemoryFault, match="unsupported"):
        memory.read(0, 8)


def test_program_segments_cannot_overwrite_mmio():
    memory = SparseDataMemory()
    with pytest.raises(MemoryFault, match="MMIO"):
        memory.load_segments([(0, b"x")])


def test_harvard_memory_keeps_instruction_and_data_spaces_separate():
    memory = HarvardMemory()
    memory.load_segments({"text": [(0x0C, b"CODE")], "data": [(0x2000, b"DATA")]})
    assert memory.instruction.read(0x0C, 4) == b"CODE"
    assert memory.data.read_bytes(0x2000, 4) == b"DATA"