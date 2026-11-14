import pytest

from main.isa import Opcode, decode
from main.translator import AsmError, translate


def section_bytes(module: dict, section: str) -> bytes:
    fragments = module["sections"][section]
    return b"".join(bytes.fromhex(fragment["data"]) for fragment in fragments)


def test_translate_basic_instructions() -> None:
    module = translate("""\
        .text
        start:
            MOVI R1, 42
            ADDI R2, R1, 1
            HALT
    """)
    code = section_bytes(module, "text")
    words = [int.from_bytes(code[i:i + 4], "little") for i in range(0, len(code), 4)]
    assert [decode(word).opcode for word in words] == [Opcode.MOVI, Opcode.ADDI, Opcode.HALT]
    assert module["symbols"]["start"] == {"section": "text", "fragment": 0, "offset": 0}


def test_translate_data_and_null_terminated_string() -> None:
    module = translate('''.rodata\nmessage:\n.asciz "Hi"\n''')
    assert section_bytes(module, "rodata") == b"Hi\\0".replace(b"\\0", b"\0")
    assert module["symbols"]["message"]["section"] == "rodata"


def test_translate_export_and_import_relocation() -> None:
    module = translate("""\
        .text
        .extern external_fn
        .global entry
        entry:
            CALL R15, external_fn
            HALT
    """)
    assert module["exports"] == ["entry"]
    assert module["imports"] == ["external_fn"]
    assert module["relocations"][0]["symbol"] == "external_fn"
    assert module["relocations"][0]["kind"] == "pcrel"


def test_undefined_symbol_is_rejected() -> None:
    with pytest.raises(AsmError, match="undefined symbol"):
        translate(".text\nJMP missing\n")


def test_unknown_instruction_is_rejected() -> None:
    with pytest.raises(AsmError, match="unknown instruction"):
        translate(".text\nFOOBAR R1, R2, R3\n")


def test_unaligned_text_org_is_rejected() -> None:
    with pytest.raises(AsmError):
        translate(".text\n.org 3\nHALT\n")


def test_equ_constant_and_li_pseudo_instruction() -> None:
    module = translate("""\
        .equ VALUE, 0x12345678
        .text
        LI R3, VALUE
    """)
    code = section_bytes(module, "text")
    words = [int.from_bytes(code[i:i + 4], "little") for i in range(0, len(code), 4)]
    assert len(words) == 2
    assert decode(words[0]).opcode is Opcode.LUI
    assert decode(words[1]).opcode is Opcode.ORI