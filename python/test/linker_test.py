from __future__ import annotations

import pytest

from main.isa import Instruction, Opcode, decode, encode
from main.linker import (
    BINARY_VERSION,
    HEADER,
    MAGIC,
    LinkError,
    from_binary,
    link,
    listing,
    to_binary,
)
from main.translator import AsmError, translate


def assemble(source: str, name: str = "module.s") -> dict[str, object]:
    return translate(source, name)


def word_at(data: bytes | bytearray, address: int, base: int = 0) -> int:
    offset = address - base
    return int.from_bytes(data[offset : offset + 4], "little")


def test_link_single_module_places_text_at_zero() -> None:
    module = assemble("""
        .text
        start:
            MOVI R1, 42
            HALT
    """, "single.s")

    program = link([module])

    assert len(program.text) == 8
    assert program.symbols["single.s::start"] == ("text", 0)
    assert decode(word_at(program.text, 0)).opcode is Opcode.MOVI
    assert decode(word_at(program.text, 4)).opcode is Opcode.HALT


def test_link_multiple_modules_places_text_sequentially() -> None:
    first = assemble(".text\nfirst:\n NOP\n", "first.s")
    second = assemble(".text\nsecond:\n HALT\n", "second.s")

    program = link([first, second])

    assert program.symbols["first.s::first"] == ("text", 0)
    assert program.symbols["second.s::second"] == ("text", 4)
    assert decode(word_at(program.text, 4)).opcode is Opcode.HALT


def test_exported_symbol_is_available_without_module_qualification() -> None:
    module = assemble("""
        .text
        .global entry
        entry:
            HALT
    """, "entry.s")

    program = link([module])

    assert program.symbols["entry"] == ("text", 0)
    assert program.exports["entry"] == ("text", 0)


def test_local_symbols_are_module_qualified() -> None:
    first = assemble(".text\nsame:\n NOP\n", "a.s")
    second = assemble(".text\nsame:\n HALT\n", "b.s")

    program = link([first, second])

    assert program.symbols["a.s::same"] == ("text", 0)
    assert program.symbols["b.s::same"] == ("text", 4)
    assert "same" not in program.symbols


def test_duplicate_exports_are_rejected() -> None:
    first = assemble(".text\n.global entry\nentry: HALT\n", "a.s")
    second = assemble(".text\n.global entry\nentry: HALT\n", "b.s")

    with pytest.raises(LinkError, match="duplicate exported symbol"):
        link([first, second])


def test_unresolved_import_is_rejected() -> None:
    module = assemble(".text\n.extern missing\n JMP missing\n", "use.s")

    with pytest.raises(LinkError, match="unresolved external symbol: missing"):
        link([module])


def test_cross_module_pcrel_call_relocation() -> None:
    caller = assemble("""
        .text
        .extern worker
        .global start
        start:
            CALL R15, worker
            HALT
    """, "caller.s")
    callee = assemble("""
        .text
        .global worker
        worker:
            RET
    """, "callee.s")

    program = link([caller, callee])
    call = decode(word_at(program.text, 0))

    assert call.opcode is Opcode.CALL
    assert call.rd == 15
    assert call.imm == 4  # target 8 - (PC 0 + 4)
    assert program.symbols["worker"] == ("text", 8)


def test_local_branch_relocation_is_resolved() -> None:
    module = assemble("""
        .text
        start:
            BEQ R1, R2, target
            NOP
        target:
            HALT
    """, "branch.s")

    program = link([module])
    branch = decode(word_at(program.text, 0))

    assert branch.opcode is Opcode.BEQ
    assert branch.imm == 4


def test_word32_relocation_writes_symbol_address() -> None:
    module = assemble("""
        .text
        .org 0
        .word target
        .org 0x20
        target:
            HALT
    """, "word.s")

    program = link([module])

    assert word_at(program.text, 0) == 0x20
    assert program.symbols["word.s::target"] == ("text", 0x20)


def test_rodata_data_and_bss_are_placed_in_distinct_regions() -> None:
    module = assemble('''
        .rodata
        message: .asciz "Hi"
        .data
        value: .word 123
        .bss
        buffer: .space 16
    ''', "sections.s")

    program = link([module])

    assert program.symbols["sections.s::message"] == ("rodata", 0x1000)
    assert program.symbols["sections.s::value"] == ("data", 0x2000)
    assert program.symbols["sections.s::buffer"] == ("bss", 0x3000)
    assert program.rodata[:3] == b"Hi\0"
    assert program.data[:4] == (123).to_bytes(4, "little")
    assert len(program.bss) == 16
    assert program.bss == bytes(16)


def test_org_places_fragment_at_requested_address() -> None:
    module = assemble(".text\n.org 0x40\nentry: HALT\n", "org.s")

    program = link([module])

    assert program.symbols["org.s::entry"] == ("text", 0x40)
    assert program.sections["text"] == [(0x40, bytearray(encode(Instruction(Opcode.HALT)).to_bytes(4, "little")))]


def test_text_fragments_are_not_allowed_to_overlap() -> None:
    module = assemble("""
        .text
        .org 0x20
        NOP
        .org 0x20
        HALT
    """, "overlap.s")

    with pytest.raises(LinkError, match="overlap"):
        link([module])


def test_text_fragment_must_be_word_aligned() -> None:
    with pytest.raises(AsmError, match="invalid .org address"):
        assemble(".text\n.org 2\nNOP\n", "unaligned.s")


def test_text_out_of_instruction_memory_range_is_rejected() -> None:
    module = assemble(".text\n.org 0x10000\nNOP\n", "too_large.s")

    with pytest.raises(LinkError, match="outside"):
        link([module])


def test_empty_input_is_rejected() -> None:
    with pytest.raises(LinkError, match="nothing to link"):
        link([])


def test_unknown_object_format_is_rejected() -> None:
    module = assemble(".text\nHALT\n")
    module["format"] = "UNKNOWN"

    with pytest.raises(LinkError, match="unsupported object format"):
        link([module])


def test_binary_round_trip_preserves_all_sections_and_addresses() -> None:
    module = assemble('''
        .text
        .org 0x0C
        start: HALT
        .rodata
        text: .asciz "hello"
        .data
        number: .word 0x12345678
        .bss
        scratch: .space 8
    ''', "binary.s")
    program = link([module])

    binary = to_binary(program)
    loaded = from_binary(binary)

    assert binary[:4] == MAGIC
    magic, version, segment_count = HEADER.unpack_from(binary)
    assert magic == MAGIC
    assert version == BINARY_VERSION
    assert segment_count == 4
    assert loaded["text"] == [(0x0C, bytes(program.text))]
    assert loaded["rodata"] == [(0x1000, bytes(program.rodata))]
    assert loaded["data"] == [(0x2000, bytes(program.data))]
    assert loaded["bss"] == [(0x3000, bytes(program.bss))]


def test_binary_parser_rejects_truncated_header() -> None:
    with pytest.raises(LinkError, match="truncated CSA4 binary"):
        from_binary(b"CSA")


def test_binary_parser_rejects_wrong_magic_or_version() -> None:
    wrong_magic = HEADER.pack(b"NOPE", BINARY_VERSION, 0)
    wrong_version = HEADER.pack(MAGIC, BINARY_VERSION + 1, 0)

    with pytest.raises(LinkError, match="not a supported"):
        from_binary(wrong_magic)
    with pytest.raises(LinkError, match="not a supported"):
        from_binary(wrong_version)


def test_binary_parser_rejects_trailing_bytes() -> None:
    binary = HEADER.pack(MAGIC, BINARY_VERSION, 0) + b"extra"

    with pytest.raises(LinkError, match="trailing bytes"):
        from_binary(binary)


def test_listing_contains_address_machine_code_and_mnemonic() -> None:
    module = assemble(".text\nstart:\n MOVI R1, 7\n HALT\n", "listing.s")
    program = link([module])

    result = listing(program)

    assert "listing.s::start:" in result
    assert "00000000 - " in result
    assert "movi" in result.lower()
    assert "halt" in result.lower()


def test_source_locations_are_mapped_to_linked_addresses() -> None:
    module = assemble(".text\nstart:\n MOVI R1, 7\n", "source.s")

    program = link([module])

    assert program.source[0].module == "source.s"
    assert program.source[0].text.lower().startswith("movi")
    assert program.source[0].line == 3


def test_abs_relocation_resolves_data_symbol_address() -> None:
    module = assemble("""
        .text
        .extern object
        MOVI R1, object
    """, "abs.s")
    target = assemble("""
        .data
        .global object
        object: .word 1
    """, "object.s")

    program = link([module, target])
    instruction = decode(word_at(program.text, 0))

    assert instruction.opcode is Opcode.MOVI
    assert instruction.imm == 0x2000


def test_hi_lo_relocations_resolve_full_address() -> None:
    module = assemble("""
        .text
        .extern object
        LUI R1, %hi(object)
        ORI R1, R1, %lo(object)
    """, "address.s")
    target = assemble("""
        .data
        .global object
        object: .word 1
    """, "object.s")

    program = link([module, target])
    lui = decode(word_at(program.text, 0))
    ori = decode(word_at(program.text, 4))
    address = (lui.imm << 18) | ori.imm

    assert address == 0x2000


def test_listing_formats_rodata_and_data() -> None:
    module = assemble('''.rodata\nmsg: .asciz "A"\n.data\nnum: .word 65\n''', "data_listing.s")
    result = listing(link([module]))

    assert "; rodata" in result
    assert "; data" in result
    assert "A" in result