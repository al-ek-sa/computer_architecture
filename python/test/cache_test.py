import pytest
from main.cache import DataCache
from main.memory import MemoryFault, SparseDataMemory


@pytest.fixture
def memory():
    result = SparseDataMemory()
    result.write_bytes(0x1000, bytes(range(64)))
    return result


@pytest.fixture
def cache(memory):
    return DataCache(memory=memory, line_size=16, line_count=2)


def test_first_read_is_miss_and_reads_correct_value(cache):
    access = cache.read(0x1000, 4)
    assert access.value == 0x03020100
    assert not access.hit
    assert access.latency == 10
    assert cache.stats.misses == 1


def test_second_read_from_same_line_is_hit(cache):
    cache.read(0x1000, 4)
    access = cache.read(0x1004, 4)
    assert access.hit
    assert access.latency == 1
    assert access.value == 0x07060504
    assert cache.stats.hits == 1


def test_read_miss_then_hit_statistics(cache):
    cache.read(0x1000)
    cache.read(0x1000)
    assert cache.stats.accesses == 2
    assert cache.stats.hits == 1
    assert cache.stats.misses == 1
    assert cache.stats.hit_rate == 0.5


def test_write_allocate_updates_cached_value_and_flushes_to_memory(cache, memory):
    first = cache.write(0x1000, 0xAABBCCDD, 4)
    assert not first.hit
    assert memory.read(0x1000, 4) == 0x03020100  # write-back: backing memory unchanged
    second = cache.read(0x1000, 4)
    assert second.hit
    assert second.value == 0xAABBCCDD
    cache.flush()
    assert memory.read(0x1000, 4) == 0xAABBCCDD


def test_conflicting_line_evicts_dirty_line_with_writeback(cache, memory):
    cache.write(0x1000, 0x11223344, 4)
    # 0x1020 maps to the same direct-mapped index as 0x1000.
    cache.read(0x1020, 4)
    assert cache.stats.writebacks == 1
    assert memory.read(0x1000, 4) == 0x11223344


def test_invalidate_writes_back_dirty_matching_line(cache, memory):
    cache.write(0x1000, 0x55667788, 4)
    cache.invalidate(0x1000)
    assert memory.read(0x1000, 4) == 0x55667788
    assert not cache.lines[0].valid


def test_clear_stats_does_not_clear_cached_data(cache):
    cache.read(0x1000)
    cache.clear_stats()
    assert cache.stats.accesses == 0
    access = cache.read(0x1000)
    assert access.hit


def test_cache_rejects_invalid_dimensions(memory):
    with pytest.raises(ValueError):
        DataCache(memory, line_size=3, line_count=2)
    with pytest.raises(ValueError):
        DataCache(memory, line_size=16, line_count=0)


def test_cache_rejects_unsupported_access_width(cache):
    with pytest.raises(MemoryFault, match="unsupported"):
        cache.read(0x1000, 8)
    with pytest.raises(MemoryFault, match="unsupported"):
        cache.write(0x1000, 1, 8)


def test_cache_access_out_of_32_bit_range_fails(cache):
    with pytest.raises(MemoryFault, match="out of range"):
        cache.read(0x1_0000_0000, 1)


def test_cross_line_read_combines_bytes_from_both_lines(memory):
    cache = DataCache(memory=memory, line_size=4, line_count=2)
    access = cache.read(0x1003, 2)
    assert access.value == 0x0403
    assert access.latency == 20
    assert not access.hit


def test_cross_line_write_updates_both_cache_lines_and_flushes(memory):
    cache = DataCache(memory=memory, line_size=4, line_count=2)
    access = cache.write(0x1003, 0xBBAA, 2)
    assert access.latency == 20
    assert memory.read_bytes(0x1003, 2) == bytes((3, 4))
    assert cache.read(0x1003, 2).value == 0xBBAA
    cache.flush()
    assert memory.read_bytes(0x1003, 2) == bytes((0xAA, 0xBB))


def test_discard_invalidate_does_not_write_back_dirty_line(memory):
    cache = DataCache(memory=memory, line_size=16, line_count=2)
    cache.write(0x1000, 0xDEADBEEF, 4)
    cache.invalidate(0x1000, writeback=False)
    assert memory.read(0x1000, 4) == 0x03020100
    assert not cache.lines[0].valid
