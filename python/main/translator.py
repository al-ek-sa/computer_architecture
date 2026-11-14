from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .isa import (
    FORMATS,
    REGISTER_INDEX,
    WORD_MASK,
    WORD_SIZE,
    Format,
    Instruction,
    Opcode,
    encode,
    lower,
    upper,
)

TEXT = "text"
RODATA = "rodata"
DATA = "data"
BSS = "bss"
SECTIONS = (TEXT, RODATA, DATA, BSS)

BYTE_MIN = -128
BYTE_MAX = 0xFF
ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "0": "\0",
    "\\": "\\", '"': '"', "'": "'",
}
IDENTIFIER = re.compile(r"[A-Za-z_.$][\w.$]*")
LABEL = re.compile(r"([A-Za-z_.$][\w.$]*):")
MEMORY = re.compile(r"^(.*?)\s*\(\s*([A-Za-z_.$][\w.$]*)\s*\)$")
MODIFIER = re.compile(r"%(hi|lo)\(\s*([A-Za-z_.$][\w.$]*)\s*\)")
USAGE = "usage: translator.py <input.s> <output.o>"


class AsmError(Exception):
    """Assembly source or relocation error."""


@dataclass(frozen=True, slots=True)
class Ref:
    symbol: str
    modifier: str = ""


Value = int | Ref
Parsed = tuple[Instruction, Ref | None]
Expansion = list[tuple[str, list[str]]]


@dataclass(frozen=True, slots=True)
class Location:
    section: str
    fragment: int
    offset: int

    def to_json(self) -> dict[str, str | int]:
        return {
            "section": self.section,
            "fragment": self.fragment,
            "offset": self.offset,
        }


@dataclass(slots=True)
class Fragment:
    org: int | None
    data: bytearray = field(default_factory=bytearray)


@dataclass(frozen=True, slots=True)
class Relocation:
    location: Location
    kind: str
    symbol: str


@dataclass(frozen=True, slots=True)
class SourceLine:
    location: Location
    line: int
    text: str


def _unquoted_positions(text: str):
    quote = ""
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
        elif quote:
            if char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        else:
            yield index, char


def strip_comment(line: str) -> str:
    for index, char in _unquoted_positions(line):
        if char == ";":
            return line[:index]
    return line


def split_operands(text: str) -> list[str]:
    if not text.strip():
        return []
    cuts = [i for i, char in _unquoted_positions(text) if char == ","]
    bounds = zip([-1, *cuts], [*cuts, len(text)], strict=True)
    return [text[start + 1:end].strip() for start, end in bounds]


def expect(operands: list[str], count: int) -> None:
    if len(operands) != count:
        raise AsmError(f"expected {count} operands, got {len(operands)}")


def quoted_body(token: str, quote: str) -> str | None:
    if len(token) >= 2 and token[0] == quote and token[-1] == quote:
        return token[1:-1]
    return None


def unescape(body: str) -> str:
    result: list[str] = []
    i = 0
    while i < len(body):
        char = body[i]
        if char != "\\":
            result.append(char)
            i += 1
            continue
        i += 1
        if i >= len(body) or body[i] not in ESCAPES:
            bad = body[i] if i < len(body) else "<end>"
            raise AsmError(f"unknown escape sequence: \\{bad}")
        result.append(ESCAPES[body[i]])
        i += 1
    return "".join(result)


def parse_number(token: str) -> int | None:
    body = quoted_body(token, "'")
    if body is not None:
        char = unescape(body)
        if len(char) != 1:
            raise AsmError(f"bad character literal: {token}")
        return ord(char)
    try:
        return int(token, 0)
    except ValueError:
        return None


def split_half(value: int, part: str) -> int:
    return upper(value) if part == "hi" else lower(value)


def relocation_kind(opcode: Opcode, ref: Ref) -> str:
    if FORMATS[opcode] in {Format.BRANCH, Format.JUMP}:
        return "pcrel"
    return ref.modifier or "abs"


def _build(opcode: Opcode, value: Value, **registers: int) -> Parsed:
    if isinstance(value, Ref):
        return Instruction(opcode, **registers), value
    return Instruction(opcode, imm=value, **registers), None


class Assembler:
    def __init__(self, name: str, defines: dict[str, int] | None = None) -> None:
        self.name = name
        self.defines = dict(defines or {})
        self.macros: dict[str, tuple[list[str], list[str]]] = {}
        self.sections: dict[str, list[Fragment]] = {section: [] for section in SECTIONS}
        self.section = TEXT
        self.symbols: dict[str, Location] = {}
        self.equs: dict[str, int] = {}
        self.exports: set[str] = set()
        self.imports: set[str] = set()
        self.relocations: list[Relocation] = []
        self.source: list[SourceLine] = []

    def current(self) -> Fragment:
        fragments = self.sections[self.section]
        if not fragments:
            fragments.append(Fragment(None))
        return fragments[-1]

    def location(self) -> Location:
        fragment = self.current()
        return Location(self.section, len(self.sections[self.section]) - 1, len(fragment.data))

    def emit(self, data: bytes) -> None:
        if self.section == BSS:
            if any(data):
                raise AsmError("initialized data is not allowed in .bss")
        self.current().data.extend(data)

    def define(self, name: str) -> None:
        if name in self.symbols or name in self.equs or name in self.imports:
            raise AsmError(f"duplicate or imported symbol: {name}")
        self.symbols[name] = self.location()

    def identifier(self, token: str) -> str:
        if not IDENTIFIER.fullmatch(token):
            raise AsmError(f"bad identifier: {token}")
        return token

    def register(self, token: str) -> int:
        key = token.lower()
        if key not in REGISTER_INDEX:
            raise AsmError(f"unknown register: {token}")
        return REGISTER_INDEX[key]

    def value(self, token: str) -> Value:
        number = parse_number(token)
        if number is not None:
            return number
        if token in self.equs:
            return self.equs[token]
        if match := MODIFIER.fullmatch(token):
            modifier, symbol = match.groups()
            if symbol in self.equs:
                return split_half(self.equs[symbol], modifier)
            return Ref(symbol, modifier)
        return Ref(self.identifier(token))

    def constant(self, token: str) -> int:
        value = self.value(token)
        if isinstance(value, Ref):
            raise AsmError(f"constant expected, got symbol: {token}")
        return value

    def label(self, token: str) -> Ref:
        value = self.value(token)
        if not isinstance(value, Ref) or value.modifier:
            raise AsmError(f"label expected: {token}")
        return value

    def memory_operand(self, token: str) -> tuple[Value, int]:
        match = MEMORY.fullmatch(token)
        if not match:
            raise AsmError(f"memory operand expected as offset(base): {token}")
        offset_text, base_text = match.groups()
        offset = self.value(offset_text.strip()) if offset_text.strip() else 0
        return offset, self.register(base_text)

    def statement(self, line_number: int, raw: str) -> None:
        line = strip_comment(raw).strip()
        while match := LABEL.match(line):
            self.define(match.group(1))
            line = line[match.end():].strip()
        if not line:
            return
        head, *tail = line.split(maxsplit=1)
        name = head.lower()
        operands = split_operands(tail[0] if tail else "")
        if name.startswith("."):
            self.directive(name, operands)
            return
        if self.section != TEXT:
            raise AsmError("instructions are allowed only in .text")
        location = self.location()
        self.source.append(SourceLine(location, line_number, line))
        self.instruction(name, operands)

    def assemble(self, source: str) -> None:
        expanded = self.preprocess(source)
        for number, raw in expanded:
            try:
                self.statement(number, raw)
            except (AsmError, ValueError) as error:
                raise AsmError(f"{self.name}:{number}: {error}") from None
        self.check()

    def preprocess(self, source: str) -> list[tuple[int, str]]:
        """Expand simple parameterized macros and conditional assembly blocks."""
        source_lines = list(enumerate(source.splitlines(), start=1))
        output: list[tuple[int, str]] = []
        active_stack: list[dict[str, bool]] = []
        active = True
        index = 0

        while index < len(source_lines):
            number, raw = source_lines[index]
            clean = strip_comment(raw).strip()
            index += 1
            if not clean:
                if active:
                    output.append((number, raw))
                continue

            head, *tail = clean.split(maxsplit=1)
            directive = head.lower()
            rest = tail[0] if tail else ""

            if directive == ".macro":
                parts = rest.split(None, 1)
                if not parts:
                    raise AsmError(f"{self.name}:{number}: .macro requires a name")
                macro_name = parts[0].lower()
                params = split_operands(parts[1]) if len(parts) > 1 else []
                body: list[str] = []
                while index < len(source_lines):
                    _, body_line = source_lines[index]
                    index += 1
                    if strip_comment(body_line).strip().lower() == ".endm":
                        break
                    body.append(body_line)
                else:
                    raise AsmError(f"{self.name}:{number}: unterminated .macro")
                if active:
                    if macro_name in self.macros:
                        raise AsmError(f"{self.name}:{number}: duplicate macro {macro_name}")
                    self.macros[macro_name] = (params, body)
                continue

            if directive == ".endm":
                raise AsmError(f"{self.name}:{number}: .endm without .macro")

            if directive in {".if", ".ifdef", ".ifndef"}:
                parent_active = active
                if directive == ".ifdef":
                    condition = rest.strip() in self.defines
                elif directive == ".ifndef":
                    condition = rest.strip() not in self.defines
                else:
                    try:
                        condition = int(rest.strip(), 0) != 0
                    except ValueError:
                        condition = self.defines.get(rest.strip(), 0) != 0
                frame = {"parent": parent_active, "condition": condition, "else": False}
                active_stack.append(frame)
                active = parent_active and condition
                continue

            if directive == ".else":
                if not active_stack or active_stack[-1]["else"]:
                    raise AsmError(f"{self.name}:{number}: unexpected .else")
                frame = active_stack[-1]
                frame["else"] = True
                active = frame["parent"] and not frame["condition"]
                continue

            if directive == ".endif":
                if not active_stack:
                    raise AsmError(f"{self.name}:{number}: unexpected .endif")
                frame = active_stack.pop()
                active = frame["parent"]
                continue

            if not active:
                continue

            invocation = clean.split(maxsplit=1)
            macro_name = invocation[0].lower()
            if macro_name in self.macros:
                params, body = self.macros[macro_name]
                args = split_operands(invocation[1] if len(invocation) > 1 else "")
                if len(args) != len(params):
                    raise AsmError(
                        f"{self.name}:{number}: macro {macro_name} expects "
                        f"{len(params)} arguments, got {len(args)}"
                    )
                replacements = dict(zip(params, args, strict=True))
                for body_line in body:
                    expanded_line = body_line
                    for position, argument in enumerate(args, start=1):
                        expanded_line = expanded_line.replace(f"\\{position}", argument)
                    for parameter, argument in replacements.items():
                        expanded_line = expanded_line.replace(f"\\{parameter}", argument)
                        expanded_line = re.sub(
                            rf"\\b{re.escape(parameter)}\\b", argument, expanded_line
                        )
                    output.append((number, expanded_line))
            else:
                output.append((number, raw))

        if active_stack:
            raise AsmError(f"{self.name}: unterminated conditional assembly block")
        return output

    def instruction(self, name: str, operands: list[str]) -> None:
        for mnemonic, args in self.expand_pseudo(name, operands):
            self.real_instruction(mnemonic, args)

    def expand_pseudo(self, name: str, operands: list[str]) -> Expansion:
        if name == "nop":
            expect(operands, 0)
            return [("nop", [])]
        if name == "ret":
            expect(operands, 0)
            return [("ret", [])]
        if name == "iret":
            expect(operands, 0)
            return [("iret", [])]
        if name == "halt":
            expect(operands, 0)
            return [("halt", [])]
        if name == "j":
            expect(operands, 1)
            return [("jmp", operands)]
        if name == "call":
            if len(operands) == 1:
                return [("call", ["R15", operands[0]])]
            expect(operands, 2)
            return [("call", operands)]
        if name == "mv":
            expect(operands, 2)
            return [("addi", [operands[0], operands[1], "0"])]
        if name == "beqz":
            expect(operands, 2)
            return [("beq", [operands[0], "R0", operands[1]])]
        if name == "bnez":
            expect(operands, 2)
            return [("bne", [operands[0], "R0", operands[1]])]
        if name in {"li", "la"}:
            expect(operands, 2)
            rd, token = operands
            value = self.value(token)
            if isinstance(value, Ref):
                return [
                    ("lui", [rd, f"%hi({value.symbol})"]),
                    ("ori", [rd, rd, f"%lo({value.symbol})"]),
                ]
            if not -(1 << 31) <= value <= WORD_MASK:
                raise AsmError(f"li/la value is outside 32-bit range: {value}")
            value &= WORD_MASK
            return [
                ("lui", [rd, str(upper(value))]),
                ("ori", [rd, rd, str(lower(value))]),
            ]
        return [(name, operands)]

    def real_instruction(self, name: str, operands: list[str]) -> None:
        try:
            opcode = Opcode[name.upper()]
        except KeyError:
            raise AsmError(f"unknown instruction: {name}") from None

        try:
            instruction, reference = self.parse_instruction(opcode, operands)
            word = encode(instruction)
        except (ValueError, TypeError) as error:
            raise AsmError(str(error)) from None

        if reference is not None:
            self.relocations.append(
                Relocation(self.location(), relocation_kind(opcode, reference), reference.symbol)
            )
        self.emit(word.to_bytes(WORD_SIZE, "little"))

    def parse_instruction(self, opcode: Opcode, operands: list[str]) -> Parsed:
        fmt = FORMATS[opcode]

        if fmt is Format.REGISTER:
            if opcode in {Opcode.NOP, Opcode.RET, Opcode.IRET, Opcode.HALT}:
                expect(operands, 0)
                return Instruction(opcode), None
            if opcode == Opcode.NOT:
                expect(operands, 2)
                return Instruction(
                    opcode, rd=self.register(operands[0]), rs1=self.register(operands[1])
                ), None
            expect(operands, 3)
            rd, rs1, rs2 = (self.register(item) for item in operands)
            return Instruction(opcode, rd=rd, rs1=rs1, rs2=rs2), None

        if fmt is Format.IMMEDIATE:
            if opcode in {Opcode.LOAD, Opcode.LOADB}:
                expect(operands, 2)
                offset, base = self.memory_operand(operands[1])
                return _build(opcode, offset, rd=self.register(operands[0]), rs1=base)
            if opcode == Opcode.MOVI:
                expect(operands, 2)
                return _build(opcode, self.value(operands[1]), rd=self.register(operands[0]))
            expect(operands, 3)
            return _build(
                opcode, self.value(operands[2]),
                rd=self.register(operands[0]), rs1=self.register(operands[1])
            )

        if fmt is Format.STORE:
            expect(operands, 2)
            offset, base = self.memory_operand(operands[1])
            return _build(opcode, offset, rs1=base, rs2=self.register(operands[0]))

        if fmt is Format.BRANCH:
            expect(operands, 3)
            return Instruction(
                opcode, rs1=self.register(operands[0]), rs2=self.register(operands[1])
            ), self.label(operands[2])

        if fmt is Format.JUMP:
            if opcode == Opcode.JMP:
                expect(operands, 1)
                return Instruction(opcode), self.label(operands[0])
            expect(operands, 2)
            return Instruction(opcode, rd=self.register(operands[0])), self.label(operands[1])

        if fmt is Format.UPPER:
            expect(operands, 2)
            return _build(opcode, self.value(operands[1]), rd=self.register(operands[0]))

        raise AsmError(f"unsupported instruction format for {opcode.mnemonic}")

    def directive(self, name: str, operands: list[str]) -> None:
        handlers: dict[str, Callable[[list[str]], None]] = {
            ".text": self.dir_text,
            ".rodata": self.dir_rodata,
            ".data": self.dir_data,
            ".bss": self.dir_bss,
            ".org": self.dir_org,
            ".equ": self.dir_equ,
            ".global": self.dir_global,
            ".globl": self.dir_global,
            ".extern": self.dir_extern,
            ".byte": self.dir_byte,
            ".ascii": self.dir_ascii,
            ".asciz": self.dir_asciz,
            ".string": self.dir_asciz,
            ".word": self.dir_word,
            ".space": self.dir_space,
            ".zero": self.dir_space,
            ".align": self.dir_align,
        }
        handler = handlers.get(name)
        if handler is None:
            raise AsmError(f"unknown directive: {name}")
        handler(operands)

    def _switch(self, section: str, operands: list[str]) -> None:
        expect(operands, 0)
        self.section = section

    def dir_text(self, operands: list[str]) -> None:
        self._switch(TEXT, operands)

    def dir_rodata(self, operands: list[str]) -> None:
        self._switch(RODATA, operands)

    def dir_data(self, operands: list[str]) -> None:
        self._switch(DATA, operands)

    def dir_bss(self, operands: list[str]) -> None:
        self._switch(BSS, operands)

    def dir_org(self, operands: list[str]) -> None:
        expect(operands, 1)
        address = self.constant(operands[0])
        if address < 0 or (self.section == TEXT and address % WORD_SIZE):
            raise AsmError(f"invalid .org address: {address:#x}")
        self.sections[self.section].append(Fragment(address))

    def dir_equ(self, operands: list[str]) -> None:
        expect(operands, 2)
        name = self.identifier(operands[0])
        if name in self.equs or name in self.symbols or name in self.imports:
            raise AsmError(f"duplicate symbol: {name}")
        self.equs[name] = self.constant(operands[1])

    def dir_global(self, operands: list[str]) -> None:
        if not operands:
            raise AsmError(".global requires at least one symbol")
        self.exports.update(self.identifier(item) for item in operands)

    def dir_extern(self, operands: list[str]) -> None:
        if not operands:
            raise AsmError(".extern requires at least one symbol")
        for item in operands:
            name = self.identifier(item)
            if name in self.symbols or name in self.equs:
                raise AsmError(f"extern symbol is defined locally: {name}")
            self.imports.add(name)

    def _data_directive(self) -> None:
        if self.section == TEXT:
            raise AsmError("data directive is not allowed in .text")

    def dir_byte(self, operands: list[str]) -> None:
        self._data_directive()
        if not operands:
            raise AsmError(".byte requires at least one value")
        for token in operands:
            body = quoted_body(token, '"')
            if body is not None:
                try:
                    raw = unescape(body).encode("ascii")
                except UnicodeEncodeError:
                    raise AsmError("only ASCII string literals are supported") from None
                self.emit(raw)
                continue
            value = self.constant(token)
            if not BYTE_MIN <= value <= BYTE_MAX:
                raise AsmError(f"byte value out of range: {value}")
            self.emit(bytes([value & 0xFF]))

    def dir_ascii(self, operands: list[str]) -> None:
        self._data_directive()
        if not operands:
            raise AsmError(".ascii requires at least one string")
        for token in operands:
            body = quoted_body(token, '"')
            if body is None:
                raise AsmError(f".ascii expects quoted string: {token}")
            try:
                self.emit(unescape(body).encode("ascii"))
            except UnicodeEncodeError:
                raise AsmError("only ASCII string literals are supported") from None

    def dir_asciz(self, operands: list[str]) -> None:
        self.dir_ascii(operands)
        self.emit(b"\0")

    def dir_word(self, operands: list[str]) -> None:
        if self.section == BSS:
            raise AsmError(".word cannot initialize .bss")
        if not operands:
            raise AsmError(".word requires at least one value")
        absolute = (self.current().org or 0) + len(self.current().data)
        if absolute % WORD_SIZE:
            raise AsmError("unaligned .word; use .align 4")
        for token in operands:
            value = self.value(token)
            if isinstance(value, Ref):
                if value.modifier:
                    raise AsmError("relocation modifiers are not supported in .word")
                self.relocations.append(Relocation(self.location(), "word32", value.symbol))
                value = 0
            if not -(1 << 31) <= value <= WORD_MASK:
                raise AsmError(f".word value out of range: {value}")
            self.emit((value & WORD_MASK).to_bytes(WORD_SIZE, "little"))

    def dir_space(self, operands: list[str]) -> None:
        self._data_directive()
        expect(operands, 1)
        size = self.constant(operands[0])
        if size < 0:
            raise AsmError(f"negative allocation size: {size}")
        self.emit(bytes(size))

    def dir_align(self, operands: list[str]) -> None:
        expect(operands, 1)
        alignment = self.constant(operands[0])
        if alignment <= 0 or alignment & (alignment - 1):
            raise AsmError("alignment must be a positive power of two")
        if self.section == TEXT and alignment % WORD_SIZE:
            raise AsmError("text alignment must be a multiple of instruction size (4)")
        absolute = (self.current().org or 0) + len(self.current().data)
        self.emit(bytes((-absolute) % alignment))

    def check(self) -> None:
        for name in sorted(self.exports - self.symbols.keys()):
            raise AsmError(f"{self.name}: exported symbol is not defined: {name}")
        known = self.symbols.keys() | self.imports
        for relocation in self.relocations:
            if relocation.symbol not in known:
                raise AsmError(f"{self.name}: undefined symbol: {relocation.symbol}")

    def to_object(self) -> dict[str, object]:
        return {
            "format": "CSA4-OBJ-2",
            "name": self.name,
            "sections": {
                section: [
                    {"org": fragment.org, "data": fragment.data.hex()}
                    for fragment in fragments
                ]
                for section, fragments in self.sections.items()
            },
            "symbols": {
                name: location.to_json()
                for name, location in sorted(self.symbols.items())
            },
            "equs": dict(sorted(self.equs.items())),
            "exports": sorted(self.exports),
            "imports": sorted(self.imports),
            "relocations": [
                {
                    **relocation.location.to_json(),
                    "kind": relocation.kind,
                    "symbol": relocation.symbol,
                }
                for relocation in self.relocations
            ],
            "source": [
                {
                    **line.location.to_json(),
                    "line": line.line,
                    "text": line.text,
                }
                for line in self.source
            ],
        }


def translate(
    source: str, name: str = "<memory>", defines: dict[str, int] | None = None
) -> dict[str, object]:
    assembler = Assembler(name, defines)
    assembler.assemble(source)
    return assembler.to_object()


def parse_define(text: str) -> tuple[str, int]:
    name, separator, value = text.partition("=")
    if not IDENTIFIER.fullmatch(name):
        raise argparse.ArgumentTypeError(f"invalid definition: {text}")
    try:
        return name, int(value, 0) if separator else 1
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid definition value: {text}") from None


def main() -> None:
    parser = argparse.ArgumentParser(description="CSA4 assembler: .s -> relocatable .o JSON")
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("-D", dest="defines", action="append", type=parse_define, default=[])
    args = parser.parse_args()

    try:
        source = args.source.read_text(encoding="utf-8")
        module = translate(source, args.source.name, dict(args.defines))
    except (OSError, AsmError) as error:
        parser.exit(1, f"error: {error}\n")
    args.target.write_text(json.dumps(module, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()