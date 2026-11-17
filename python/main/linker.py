from __future__ import annotations

import argparse
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .isa import (
    IMEM_SIZE,
    WORD_MASK,
    WORD_SIZE,
    Instruction,
    Opcode,
    decode,
    disassemble,
    encode,
    lower,
    upper,
)

TEXT = "text"
RODATA = "rodata"
DATA = "data"
BSS = "bss"
SECTIONS = (TEXT, RODATA, DATA, BSS)

SECTION_IDS = {TEXT: 1, RODATA: 2, DATA: 3, BSS: 4}
VECTOR_TABLE_SIZE = 3 * WORD_SIZE
SECTION_BASES = {
    TEXT: VECTOR_TABLE_SIZE,
    RODATA: 0x0000_1000,
    DATA: 0x0000_2000,
    BSS: 0x0000_3000,
}
SECTION_LIMITS = {
    TEXT: IMEM_SIZE,
    RODATA: 0x0000_2000,
    DATA: 0x0000_3000,
    BSS: 0x0000_4000,
}

MAGIC = b"CSA4"
BINARY_VERSION = 2
HEADER = struct.Struct("<4sHH")
SEGMENT = struct.Struct("<B3xII")


class LinkError(Exception):
    """Object module, symbol, layout, or relocation error."""


@dataclass(frozen=True, slots=True)
class PlacedFragment:
    module_index: int
    module_name: str
    section: str
    fragment_index: int
    address: int
    data: bytearray

    @property
    def end(self) -> int:
        return self.address + len(self.data)


@dataclass(frozen=True, slots=True)
class SourceInfo:
    module: str
    line: int
    text: str


@dataclass(slots=True)
class Program:
    sections: dict[str, list[tuple[int, bytearray]]]
    symbols: dict[str, tuple[str, int]]
    source: dict[int, SourceInfo]
    exports: dict[str, tuple[str, int]]

    @property
    def text(self) -> bytearray:
        return self.flat_section(TEXT)

    @property
    def rodata(self) -> bytearray:
        return self.flat_section(RODATA)

    @property
    def data(self) -> bytearray:
        return self.flat_section(DATA)

    @property
    def bss(self) -> bytearray:
        return self.flat_section(BSS)

    def flat_section(self, section: str) -> bytearray:
        segments = self.sections[section]
        if not segments:
            return bytearray()
        base = min(address for address, _ in segments)
        end = max(address + len(data) for address, data in segments)
        image = bytearray(end - base)
        for address, data in segments:
            image[address - base : address - base + len(data)] = data
        return image


def _as_int(value: Any, description: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LinkError(f"{description} must be an integer")
    return value


def _validate_module(module: dict[str, Any], index: int) -> None:
    if module.get("format") != "CSA4-OBJ-2":
        raise LinkError(
            f"module #{index}: unsupported object format {module.get('format')!r}"
        )
    if not isinstance(module.get("name"), str):
        raise LinkError(f"module #{index}: missing module name")

    sections = module.get("sections")
    if not isinstance(sections, dict):
        raise LinkError(f"{module['name']}: missing sections")
    for section in SECTIONS:
        fragments = sections.get(section)
        if not isinstance(fragments, list):
            raise LinkError(f"{module['name']}: section {section} must be a list")
        for fragment in fragments:
            if not isinstance(fragment, dict) or not isinstance(
                fragment.get("data"), str
            ):
                raise LinkError(f"{module['name']}: malformed {section} fragment")
            try:
                raw = bytes.fromhex(fragment["data"])
            except ValueError:
                raise LinkError(f"{module['name']}: invalid hex in {section}") from None
            if section == TEXT and len(raw) % WORD_SIZE:
                raise LinkError(
                    f"{module['name']}: text fragment size is not word-aligned"
                )
            org = fragment.get("org")
            if org is not None:
                _as_int(org, f"{module['name']} {section} .org")

    for key in ("symbols", "exports", "imports", "relocations", "source"):
        if key not in module:
            raise LinkError(f"{module['name']}: missing object field {key}")
    vectors = module.get("vectors", {})
    if not isinstance(vectors, dict):
        raise LinkError(f"{module['name']}: malformed interrupt vector declarations")
    if set(vectors) - {"INPUT"}:
        raise LinkError(f"{module['name']}: unsupported interrupt vector declaration")
    if any(not isinstance(name, str) or not name for name in vectors.values()):
        raise LinkError(f"{module['name']}: malformed interrupt handler symbol")


def _fragment_bytes(fragment: dict[str, Any]) -> bytearray:
    try:
        return bytearray.fromhex(fragment["data"])
    except (TypeError, ValueError):
        raise LinkError("invalid fragment data") from None


def place_modules(
    modules: list[dict[str, Any]],
) -> dict[tuple[int, str, int], PlacedFragment]:
    placed: dict[tuple[int, str, int], PlacedFragment] = {}
    high_water = dict(SECTION_BASES)

    for module_index, module in enumerate(modules):
        module_name = module["name"]
        for section in SECTIONS:
            cursor = high_water[section]
            for fragment_index, fragment in enumerate(module["sections"][section]):
                data = _fragment_bytes(fragment)
                requested = fragment.get("org")
                address = cursor if requested is None else requested
                if section == TEXT and address % WORD_SIZE:
                    raise LinkError(
                        f"{module_name}: text fragment address {address:#x} is unaligned"
                    )
                placed[(module_index, section, fragment_index)] = PlacedFragment(
                    module_index,
                    module_name,
                    section,
                    fragment_index,
                    address,
                    data,
                )
                cursor = max(cursor, address + len(data))
            high_water[section] = max(high_water[section], cursor)

    check_layout(list(placed.values()))
    return placed


def check_layout(fragments: list[PlacedFragment]) -> None:
    explicit_vector_tables = [
        fragment
        for fragment in fragments
        if fragment.section == TEXT and fragment.address == 0 and fragment.data
    ]
    if len(explicit_vector_tables) > 1:
        raise LinkError("multiple explicit interrupt vector tables")

    for fragment in explicit_vector_tables:
        if len(fragment.data) != VECTOR_TABLE_SIZE:
            raise LinkError(
                f"{fragment.module_name}: explicit vector table must be "
                f"exactly {VECTOR_TABLE_SIZE} bytes"
            )

    for section in SECTIONS:
        low = SECTION_BASES[section]
        high = SECTION_LIMITS[section]
        used = sorted(
            (
                fragment
                for fragment in fragments
                if fragment.section == section and fragment.data
            ),
            key=lambda item: (item.address, item.end),
        )
        for fragment in used:
            is_explicit_vector_table = (
                section == TEXT
                and fragment.address == 0
                and len(fragment.data) == VECTOR_TABLE_SIZE
            )
            if not is_explicit_vector_table and (
                fragment.address < low or fragment.end > high
            ):
                raise LinkError(
                    f"{fragment.module_name}: {section} range "
                    f"{fragment.address:#x}..{fragment.end:#x} is outside "
                    f"{low:#x}..{high:#x}"
                )
        previous: PlacedFragment | None = None
        for current in used:
            if previous is not None and current.address < previous.end:
                raise LinkError(
                    f"{section} overlap: {previous.module_name} and "
                    f"{current.module_name} at {current.address:#x}"
                )
            previous = current


def _location_address(
    module_index: int,
    location: dict[str, Any],
    placed: dict[tuple[int, str, int], PlacedFragment],
) -> int:
    try:
        section = location["section"]
        fragment_index = location["fragment"]
        offset = location["offset"]
        fragment = placed[(module_index, section, fragment_index)]
    except (KeyError, TypeError):
        raise LinkError(f"invalid object location: {location!r}") from None
    if not isinstance(offset, int) or not 0 <= offset <= len(fragment.data):
        raise LinkError(f"invalid offset in object location: {location!r}")
    return fragment.address + offset


def resolve_symbols(
    modules: list[dict[str, Any]],
    placed: dict[tuple[int, str, int], PlacedFragment],
) -> tuple[dict[tuple[int, str], tuple[str, int]], dict[str, tuple[str, int]]]:
    local: dict[tuple[int, str], tuple[str, int]] = {}
    exports: dict[str, tuple[str, int]] = {}

    for module_index, module in enumerate(modules):
        symbols = module["symbols"]
        if not isinstance(symbols, dict):
            raise LinkError(f"{module['name']}: malformed symbol table")
        for name, item in symbols.items():
            if not isinstance(item, dict):
                raise LinkError(f"{module['name']}: malformed symbol {name}")
            section = item.get("section")
            if section not in SECTIONS:
                raise LinkError(f"{module['name']}: symbol {name} has bad section")
            address = _location_address(module_index, item, placed)
            local[(module_index, name)] = (section, address)

        for name in module["exports"]:
            if name not in symbols:
                raise LinkError(
                    f"{module['name']}: exported symbol is undefined: {name}"
                )
            if name in exports:
                raise LinkError(f"duplicate exported symbol: {name}")
            exports[name] = local[(module_index, name)]

    return local, exports


def check_imports(
    modules: list[dict[str, Any]],
    exports: dict[str, tuple[str, int]],
) -> None:
    for module in modules:
        imports = module["imports"]
        if not isinstance(imports, list):
            raise LinkError(f"{module['name']}: malformed import list")
        for name in imports:
            if name not in exports:
                raise LinkError(f"{module['name']}: unresolved external symbol: {name}")


def _find_fragment(
    module_index: int,
    section: str,
    fragment_index: int,
    placed: dict[tuple[int, str, int], PlacedFragment],
) -> PlacedFragment:
    try:
        return placed[(module_index, section, fragment_index)]
    except KeyError:
        raise LinkError(
            f"relocation refers to missing fragment {module_index}:{section}:{fragment_index}"
        ) from None


def _write_word(data: bytearray, offset: int, value: int) -> None:
    if offset < 0 or offset + WORD_SIZE > len(data):
        raise LinkError("relocation writes outside its fragment")
    data[offset : offset + WORD_SIZE] = (value & WORD_MASK).to_bytes(
        WORD_SIZE, "little"
    )


def _patch_instruction(
    fragment: PlacedFragment,
    offset: int,
    kind: str,
    target: int,
) -> None:
    if offset % WORD_SIZE or offset + WORD_SIZE > len(fragment.data):
        raise LinkError("instruction relocation is not aligned or is out of range")
    word = int.from_bytes(fragment.data[offset : offset + WORD_SIZE], "little")
    try:
        instruction = decode(word)
    except ValueError as error:
        raise LinkError(f"cannot relocate invalid instruction: {error}") from None

    if kind == "pcrel":
        if instruction.opcode not in {
            Opcode.BEQ,
            Opcode.BNE,
            Opcode.BLT,
            Opcode.BGE,
            Opcode.JMP,
            Opcode.CALL,
        }:
            raise LinkError(f"PC-relative relocation on {instruction.opcode.mnemonic}")
        displacement = target - (fragment.address + offset + WORD_SIZE)
        instruction = Instruction(
            instruction.opcode,
            rd=instruction.rd,
            rs1=instruction.rs1,
            rs2=instruction.rs2,
            imm=displacement,
        )
    elif kind == "abs":
        if instruction.opcode not in {
            Opcode.MOVI,
            Opcode.ADDI,
            Opcode.ORI,
            Opcode.LOAD,
            Opcode.LOADB,
            Opcode.STORE,
            Opcode.STOREB,
        }:
            raise LinkError(
                f"absolute 18-bit relocation is not valid for {instruction.opcode.mnemonic}"
            )
        instruction = Instruction(
            instruction.opcode,
            rd=instruction.rd,
            rs1=instruction.rs1,
            rs2=instruction.rs2,
            imm=target,
        )
    elif kind == "hi":
        if instruction.opcode != Opcode.LUI:
            raise LinkError("hi relocation must target LUI")
        instruction = Instruction(
            instruction.opcode, rd=instruction.rd, imm=upper(target)
        )
    elif kind == "lo":
        if instruction.opcode != Opcode.ORI:
            raise LinkError("lo relocation must target ORI")
        instruction = Instruction(
            instruction.opcode,
            rd=instruction.rd,
            rs1=instruction.rs1,
            imm=lower(target),
        )
    else:
        raise LinkError(f"unknown instruction relocation kind: {kind}")

    try:
        _write_word(fragment.data, offset, encode(instruction))
    except ValueError as error:
        raise LinkError(
            f"relocation overflow at {fragment.address + offset:#x}: {error}"
        ) from None


def apply_relocations(
    modules: list[dict[str, Any]],
    placed: dict[tuple[int, str, int], PlacedFragment],
    local: dict[tuple[int, str], tuple[str, int]],
    exports: dict[str, tuple[str, int]],
) -> None:
    for module_index, module in enumerate(modules):
        for relocation in module["relocations"]:
            if not isinstance(relocation, dict):
                raise LinkError(f"{module['name']}: malformed relocation")
            symbol = relocation.get("symbol")
            key = (module_index, symbol)
            if key in local:
                target_section, target = local[key]
            elif symbol in exports:
                target_section, target = exports[symbol]
            else:
                raise LinkError(f"{module['name']}: unresolved symbol {symbol!r}")

            section = relocation.get("section")
            fragment_index = relocation.get("fragment")
            offset = relocation.get("offset")
            kind = relocation.get("kind")
            fragment = _find_fragment(module_index, section, fragment_index, placed)
            if not isinstance(offset, int):
                raise LinkError("relocation offset must be an integer")

            if kind == "word32":
                if offset % WORD_SIZE:
                    raise LinkError("word32 relocation is not aligned")
                _write_word(fragment.data, offset, target)
            else:
                _patch_instruction(fragment, offset, kind, target)


def _collect_program(
    modules: list[dict[str, Any]],
    placed: dict[tuple[int, str, int], PlacedFragment],
    local: dict[tuple[int, str], tuple[str, int]],
    exports: dict[str, tuple[str, int]],
) -> Program:
    sections: dict[str, list[tuple[int, bytearray]]] = {name: [] for name in SECTIONS}
    for fragment in placed.values():
        if fragment.data:
            sections[fragment.section].append((fragment.address, fragment.data))
    for section in SECTIONS:
        sections[section].sort(key=lambda item: item[0])

    symbols: dict[str, tuple[str, int]] = {}
    for (module_index, name), location in local.items():
        module_name = modules[module_index]["name"]
        symbols[f"{module_name}::{name}"] = location
        if name in modules[module_index]["exports"]:
            symbols[name] = location

    source: dict[int, SourceInfo] = {}
    for module_index, module in enumerate(modules):
        for item in module["source"]:
            address = _location_address(module_index, item, placed)
            source[address] = SourceInfo(module["name"], item["line"], item["text"])

    start_locations = [
        local[(module_index, "_start")]
        for module_index, module in enumerate(modules)
        if "_start" in module["symbols"]
    ]
    if len(start_locations) > 1:
        raise LinkError("multiple _start entry points")
    if start_locations:
        entry_section, entry_address = start_locations[0]
    else:
        text_fragments = [
            (address, data) for address, data in sections[TEXT] if address != 0 and data
        ]
        if not text_fragments:
            entry_section, entry_address = TEXT, 0
        else:
            entry_section, entry_address = (
                TEXT,
                min(address for address, _ in text_fragments),
            )
    if entry_section != TEXT:
        raise LinkError("_start must be in .text")

    input_handler: int | None = None
    for module_index, module in enumerate(modules):
        handler_name = module.get("vectors", {}).get("INPUT")
        if handler_name is None:
            continue
        if input_handler is not None:
            raise LinkError("INPUT interrupt handler declared more than once")
        if (module_index, handler_name) in local:
            handler_section, input_handler = local[(module_index, handler_name)]
        elif handler_name in exports:
            handler_section, input_handler = exports[handler_name]
        else:
            raise LinkError(
                f"{module['name']}: unresolved INPUT interrupt handler: {handler_name}"
            )
        if handler_section != TEXT:
            raise LinkError("INPUT interrupt handler must be in .text")

    explicit_vector_table = next(
        (
            data
            for address, data in sections[TEXT]
            if address == 0 and len(data) == VECTOR_TABLE_SIZE
        ),
        None,
    )

    if explicit_vector_table is None:
        vector_bytes = bytearray(VECTOR_TABLE_SIZE)
        vector_bytes[0:WORD_SIZE] = entry_address.to_bytes(WORD_SIZE, "little")
        vector_bytes[WORD_SIZE : 2 * WORD_SIZE] = (input_handler or 0).to_bytes(
            WORD_SIZE, "little"
        )
        sections[TEXT].append((0, vector_bytes))
        sections[TEXT].sort(key=lambda item: item[0])
    elif input_handler is not None:
        explicit_vector_table[WORD_SIZE : 2 * WORD_SIZE] = input_handler.to_bytes(
            WORD_SIZE, "little"
        )

    symbols["$reset_vector"] = (TEXT, 0)
    symbols["$input_vector"] = (TEXT, WORD_SIZE)

    return Program(sections, symbols, source, exports)


def link(modules: list[dict[str, Any]]) -> Program:
    if not modules:
        raise LinkError("nothing to link")
    for index, module in enumerate(modules):
        _validate_module(module, index)

    placed = place_modules(modules)
    local, exports = resolve_symbols(modules, placed)
    check_imports(modules, exports)
    apply_relocations(modules, placed, local, exports)
    return _collect_program(modules, placed, local, exports)


def to_binary(program: Program) -> bytes:
    segments: list[tuple[int, int, bytes]] = []
    for section in SECTIONS:
        for address, data in program.sections[section]:
            if data:
                segments.append((SECTION_IDS[section], address, bytes(data)))
    segments.sort(key=lambda item: (item[0], item[1]))

    header = HEADER.pack(MAGIC, BINARY_VERSION, len(segments))
    descriptors = b"".join(
        SEGMENT.pack(section_id, address, len(data))
        for section_id, address, data in segments
    )
    payload = b"".join(data for _, _, data in segments)
    return header + descriptors + payload


def from_binary(binary: bytes) -> dict[str, list[tuple[int, bytes]]]:
    if len(binary) < HEADER.size:
        raise LinkError("truncated CSA4 binary")
    magic, version, count = HEADER.unpack_from(binary)
    if magic != MAGIC or version != BINARY_VERSION:
        raise LinkError("not a supported CSA4 executable")

    descriptor_end = HEADER.size + count * SEGMENT.size
    if len(binary) < descriptor_end:
        raise LinkError("truncated CSA4 segment table")

    descriptors = []
    cursor = descriptor_end
    for index in range(count):
        section_id, address, size = SEGMENT.unpack_from(
            binary, HEADER.size + index * SEGMENT.size
        )
        if section_id not in SECTION_IDS.values():
            raise LinkError(f"unknown section id in segment #{index}")
        if cursor + size > len(binary):
            raise LinkError("truncated CSA4 segment payload")
        descriptors.append((section_id, address, binary[cursor : cursor + size]))
        cursor += size
    if cursor != len(binary):
        raise LinkError("trailing bytes after CSA4 executable")

    result: dict[str, list[tuple[int, bytes]]] = {name: [] for name in SECTIONS}
    id_to_section = {value: key for key, value in SECTION_IDS.items()}
    for section_id, address, data in descriptors:
        result[id_to_section[section_id]].append((address, data))
    return result


def listing(program: Program) -> str:
    lines: list[str] = []
    labels_by_section: dict[str, dict[int, list[str]]] = {
        section: {} for section in SECTIONS
    }
    for name, (section, address) in sorted(program.symbols.items()):
        labels_by_section[section].setdefault(address, []).append(name)

    lines.append("; instruction memory")
    for address, data in program.sections[TEXT]:
        for offset in range(0, len(data), WORD_SIZE):
            pc = address + offset
            for label in labels_by_section[TEXT].get(pc, []):
                lines.append(f"{'':18}{label}:")
            word = int.from_bytes(data[offset : offset + WORD_SIZE], "little")
            try:
                mnemonic = disassemble(decode(word), pc)
            except ValueError:
                mnemonic = f".word 0x{word:08X}"
            info = program.source.get(pc)
            suffix = f" ; {info.module}:{info.line} {info.text}" if info else ""
            lines.append(f"{pc:08X} - {word:08X} - {mnemonic}{suffix}")

    for section in (RODATA, DATA, BSS):
        lines.extend(("", f"; {section}"))
        for address, data in program.sections[section]:
            for offset in range(0, len(data), WORD_SIZE):
                chunk = data[offset : offset + WORD_SIZE]
                current = address + offset
                for label in labels_by_section[section].get(current, []):
                    lines.append(f"{'':18}{label}:")
                hex_bytes = chunk.hex().upper()
                printable = "".join(
                    chr(byte) if 0x20 <= byte < 0x7F else "." for byte in chunk
                )
                lines.append(f"{current:08X} - {hex_bytes:<8} - {printable}")
    return "\n".join(lines) + "\n"


def _load_object(path: Path) -> dict[str, Any]:
    try:
        module = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LinkError(f"cannot read object {path}: {error}") from None
    if not isinstance(module, dict):
        raise LinkError(f"{path}: object root must be a JSON object")
    return module


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CSA4 linker: object modules -> executable"
    )
    parser.add_argument("objects", nargs="+", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=Path("a.out"))
    parser.add_argument("--listing", type=Path)
    args = parser.parse_args()

    try:
        modules = [_load_object(path) for path in args.objects]
        program = link(modules)
        args.output.write_bytes(to_binary(program))
        if args.listing:
            args.listing.write_text(listing(program), encoding="utf-8")
    except (OSError, LinkError) as error:
        parser.exit(1, f"link error: {error}\n")


if __name__ == "__main__":
    main()
