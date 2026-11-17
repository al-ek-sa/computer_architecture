from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum

# Все прописанные константы описаны в документации в директории docs, подробнее можно прочитать там

# Размер машинного слова в байтах (лимитировано и прописасано в .md)
WORD_SIZE = 4
# Разрядность машинного слова в битах (прописано в .md)
WORD_BITS = 32
# Маска для ограничения значения 32 битами (все биты равны 1)
WORD_MASK = 0xFFFF_FFFF

# Размер памяти команд
IMEM_SIZE = 0x1_0000
# Размер памяти данных
DMEM_SIZE = 1 << 32

# Адрес вектора сброса
RESET_VECTOR = 0x0000
# Адрес вектора прерывания от устройства ввода
INPUT_VECTOR = 0x0004
# Адрес зарезервированного вектора прерывания
RESERVED_VECTOR = 0x0008
# Адрес начала области памяти, в которой размещается исполняемый код
TEXT_START = 0x000C

# Начальный адрес области отображения памяти на устройства ввода-вывода
MMIO_START = 0x0000_0000
# Адрес регистра данных ввода
INPUT_DATA = 0x0000_0000
# Адрес регистра данных вывода
OUTPUT_DATA = 0x0000_0004
# Адрес регистра-счётчика тактов процессора
CYCLE_COUNTER = 0x0000_0008
# Адрес регистра состояния устройства ввода
INPUT_STATUS = 0x0000_000C
# Конечная граница области MMIO
MMIO_END = 0x0000_0010

# Начало зарезервированной области памяти данных
RESERVED_START = 0x0000_0010
# Начальный адрес секции .rodata
RODATA_START = 0x0000_1000
# Конечный адрес секции .rodata
RODATA_END = 0x0000_2000
# Начальный адрес секции .data
DATA_START = 0x0000_2000
# Конечный адрес секции .data
DATA_END = 0x0000_3000
# Начальный адрес секции .bss
BSS_START = 0x0000_3000
# Конечный адрес секции .bss
BSS_END = 0x0000_4000
# Начальный адрес области динамической памяти
HEAP_START = 0x0000_4000
# Конечный адрес области динамической памяти
HEAP_END = 0x0030_0000
# Начальный адрес области стека
STACK_BASE = 0x0030_0000
# Верхняя граница стека, совпадающая с размером памяти данных
STACK_TOP = DMEM_SIZE
# Начальное значение указателя стека (SP) при запуске процессора
INITIAL_SP = STACK_TOP

# Количество регистров общего назначения
REGISTER_COUNT = 16
# Номер нулевого регистра R0
ZERO_REGISTER = 0
# Номер регистра R14
SP_REGISTER = 14
# Номер регистра R15
RA_REGISTER = 15
# Генерация имен от r0 до r15 + индексация регистров от х0 до х15 и инициалицазия специальных регистров
REGISTERS = tuple(f"R{i}" for i in range(REGISTER_COUNT))
REGISTER_INDEX = {
    **{name.lower(): index for index, name in enumerate(REGISTERS)},
    **{f"x{index}": index for index in range(REGISTER_COUNT)},
}
REGISTER_INDEX.update({"zero": 0, "sp": 14, "ra": 15})


class Opcode(Enum):
    # полная документация прописана в ../docs/isa.md ьам прописана логика проставления кода операций

    # Операция ничего не делает
    NOP = 0x00
    # Сложение двух регистров
    ADD = 0x01
    # вычитание
    SUB = 0x02
    # умножение двух регистров
    MUL = 0x03
    # Деление двух регистров буз учета остатка
    DIV = 0x04
    # Побитовое И двух регистров
    AND = 0x05
    # Побитовое ИЛИ двух регистров
    OR = 0x06
    # Побитовое исключающее ИЛИ двух регистров
    XOR = 0x07
    # Побитовое отрицание значения регистра
    NOT = 0x08
    # Логический сдвиг значения регистра влево
    SHL = 0x09
    # Логический сдвиг значения регистра вправо
    SHR = 0x0A

    # Сложение регистра с непосредственным значением
    ADDI = 0x10
    # Загрузка непосредственного значения в регистр
    MOVI = 0x11
    # Загрузка старшей части константы в регистр
    LUI = 0x12
    # Побитовое ИЛИ регистра с непосредственным значением
    ORI = 0x13
    # Чтение 32-битного слова из памяти в регистр
    LOAD = 0x14
    # Чтение одного байта из памяти в регистр с расширением нулями
    LOADB = 0x15
    # Запись 32-битного слова из регистра в память
    STORE = 0x16
    # Запись младшего байта регистра в память
    STOREB = 0x17

    # Переход, если значения двух регистров равны
    BEQ = 0x20
    # Переход, если значения двух регистров не равны
    BNE = 0x21
    # Переход, если значение первого регистра меньше второго
    BLT = 0x22
    # Переход, если значение первого регистра больше или равно второму
    BGE = 0x23
    # Запись 1 в rd, если rs1 < rs2, иначе 0
    SLT = 0x24
    # Запись 1 в rd, если rs1 < rs2, иначе 0
    SLTU = 0x25

    # Безусловный переход по заданному смещению
    JMP = 0x30
    # Вызов подпрограммы: сохраняет адрес возврата и выполняет переход
    CALL = 0x31
    # Возврат из подпрограммы по адресу, сохранённому в RA
    RET = 0x32
    # Возврат из обработчика прерывания с восстановлением сохранённого PC
    IRET = 0x33
    # Остановка
    HALT = 0x34

    @property
    def mnemonic(self) -> str:
        return self.name.lower()


class Format(Enum):
    # Данные форматы описаны в документации ../dpcs/isa.md
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

# Словарь соответствия числового кода операции элементу перечисления Opcode
OPCODES = {opcode.value: opcode for opcode in Opcode}
# Словарь соответствия мнемоники инструкции элементу перечисления Opcode
MNEMONICS = {opcode.mnemonic: opcode for opcode in Opcode}
# Неизменяемое множество инструкций чтения из памяти
LOADS = frozenset({Opcode.LOAD, Opcode.LOADB})
# Неизменяемое множество инструкций записи в память
STORES = frozenset({Opcode.STORE, Opcode.STOREB})

# Количество бит для знакового непосредственного операнда (от -2^17 до 2^17 - 1)
SIGNED_IMMEDIATE_BITS = 18
# Количество бит для беззнакового непосредственного операнда (от 0 до 2^18 - 1)
UNSIGNED_IMMEDIATE_BITS = 18
# Количество бит для смещения условного перехода (формат B)
BRANCH_DISPLACEMENT_BITS = 18
# Количество бит для смещения безусловного перехода или вызова подпрограммы (формат J)
JUMP_DISPLACEMENT_BITS = 22
# Количество бит для непосредственного значения в инструкции загрузки старшей части константы (формат U)
UPPER_IMMEDIATE_BITS = 14


# Исключение при обнаружении некорректной инструкции
class ISAError(ValueError):
    """Invalid instruction or instruction encoding."""


# Иммутабельное описание одной машинной инструкции
# frozen=True делает объект иммутабельным
# slots=True оптимизирует хранение атрибутов экземпляра
@dataclass(frozen=True, slots=True)
class Instruction:
    opcode: Opcode
    rd: int = 0
    rs1: int = 0
    rs2: int = 0

    # Непосредственное значение, смещение или адресный операнд.
    imm: int = 0

    def __post_init__(self) -> None:
        # Проверяем, что номера всех используемых полей регистров находятся в допустимом диапазоне
        for field_name, register in (
            ("rd", self.rd),
            ("rs1", self.rs1),
            ("rs2", self.rs2),
        ):
            # Если номер регистра выходит за допустимые границы, генер. исключение
            if not 0 <= register < REGISTER_COUNT:
                raise ISAError(f"{field_name} register out of range: {register}")


# Проверяет, помещается ли значение в заданное количество беззнаковых бит
def _check_unsigned(value: int, width: int, what: str) -> int:
    # Беззнаковое число должно находиться в диапазоне [0, 2^width - 1]
    if not 0 <= value < (1 << width):
        raise ISAError(f"{what} {value} does not fit into {width} unsigned bits")
    return value


# Проверяет, помещается ли значение в заданное количество знаковых бит
def _check_signed(value: int, width: int, what: str) -> int:
    limit = 1 << (width - 1)
    # Проверяем диапазон от -2^(width-1) до 2^(width-1) - 1
    if not -limit <= value < limit:
        raise ISAError(f"{what} {value} does not fit into {width} signed bits")
    return value & ((1 << width) - 1)


# Выполняет знаковое расширение числа из заданной разрядности
def _sign_extend(value: int, width: int) -> int:
    sign = 1 << (width - 1)
    return (value ^ sign) - sign


# Проверяет смещение относительно PC на соответствие требованиям архитектуры
def _check_displacement(value: int, width: int) -> int:
    if value % WORD_SIZE:
        raise ISAError(
            f"PC-relative displacement must be {WORD_SIZE}-byte aligned: {value}"
        )
    return _check_signed(value, width, "displacement")


# Проверяет, что инструкция не содержит лишних операндов
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
    elif op == Opcode.JMP and instr.rd:
        raise ISAError("jmp has no destination register; rd must be R0")


# Преобразует объект Instruction в 32-битное машинное слово
def encode(instr: Instruction) -> int:
    # Проверка отсутствия лишних операндов
    _validate_unused(instr)
    op = instr.opcode.value
    fmt = FORMATS[instr.opcode]
    word = op << 26

    if fmt is Format.REGISTER:
        # Записываем 4-битный индекс регистра назначения в биты 22–25
        word |= instr.rd << 22
        # Записываем индекс первого регистра-операнда в биты 18–21
        word |= instr.rs1 << 18
        # Записываем индекс второго регистра-операнда в биты 14–17
        word |= instr.rs2 << 14

    elif fmt is Format.IMMEDIATE:
        # ORI использует беззнаковое непосредственное значение
        if instr.opcode == Opcode.ORI:
            immediate = _check_unsigned(
                instr.imm, UNSIGNED_IMMEDIATE_BITS, "ORI immediate"
            )
        # Остальные инструкции формата I используют знаковое значение
        else:
            immediate = _check_signed(instr.imm, SIGNED_IMMEDIATE_BITS, "immediate")
        # Записываем регистр назначения в биты 22–25
        word |= instr.rd << 22
        # Записываем первый регистр-операнд в биты 18–21
        word |= instr.rs1 << 18
        # Записываем 18-битное непосредственное значение в младшие биты
        word |= immediate

    # Кодирование инструкций формата S
    elif fmt is Format.STORE:
        # Проверяем знаковое смещение относительно базового регистра
        offset = _check_signed(instr.imm, SIGNED_IMMEDIATE_BITS, "store offset")
        # Записываем базовый регистр в биты 22–25
        word |= instr.rs1 << 22
        # Записываем регистр с данными в биты 18–21
        word |= instr.rs2 << 18
        # Записываем смещение в младшие 18 бит
        word |= offset

    # Кодирование инструкций формата B
    elif fmt is Format.BRANCH:
        # Проверяем смещение условного перехода (должно быть выровнено и помещаться в 18 знаковых бит)
        displacement = _check_displacement(instr.imm, BRANCH_DISPLACEMENT_BITS)
        # Записываем первый регистр для сравнения
        word |= instr.rs1 << 22
        # Записываем второй регистр для сравнения
        word |= instr.rs2 << 18
        # Записываем смещение перехода в младшие 18 бит
        word |= displacement

    # Кодирование инструкций формата J
    elif fmt is Format.JUMP:
        # Проверяем смещение безусловного перехода или вызова
        displacement = _check_displacement(instr.imm, JUMP_DISPLACEMENT_BITS)
        # Записываем регистр назначения
        word |= instr.rd << 22
        # Записываем 22-битное смещение перехода
        word |= displacement

    # Кодирование инструкций формата U
    elif fmt is Format.UPPER:
        # Проверяем, что непосредственное значение помещается в 14 беззнаковых бит
        immediate = _check_unsigned(instr.imm, UPPER_IMMEDIATE_BITS, "LUI immediate")
        # Записываем регистр назначения
        word |= instr.rd << 22
        # Размещаем 14-битное значение в битах 8–21
        word |= immediate << 8

    else:
        raise ISAError(f"unsupported instruction format: {fmt}")

    # Оставляем только младшие 32 бита и возвращаем машинное слово
    return word & WORD_MASK


# Преобразует 32-битное машинное слово обратно в объект Instruction
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

    # Декодирование инструкций формата R
    if fmt is Format.REGISTER:
        if word & 0x3FFF:
            raise ISAError(f"nonzero reserved bits in {opcode.mnemonic}")
        instr = Instruction(opcode, rd=rd, rs1=rs1, rs2=rs2)

    # Декодирование инструкций формата I
    elif fmt is Format.IMMEDIATE:
        raw_imm = word & 0x3FFFF
        immediate = raw_imm if opcode == Opcode.ORI else _sign_extend(raw_imm, 18)
        instr = Instruction(opcode, rd=rd, rs1=rs1, imm=immediate)

    # Декодирование инструкций формата S
    elif fmt is Format.STORE:
        instr = Instruction(opcode, rs1=rd, rs2=rs1, imm=imm18)

    # Декодирование инструкций формата B
    elif fmt is Format.BRANCH:
        instr = Instruction(opcode, rs1=rd, rs2=rs1, imm=imm18)
        if instr.imm % WORD_SIZE:
            raise ISAError("branch displacement is not word-aligned")

    # Декодирование инструкций формата J
    elif fmt is Format.JUMP:
        raw = word & 0x3F_FFFF
        displacement = _sign_extend(raw, JUMP_DISPLACEMENT_BITS)
        instr = Instruction(opcode, rd=rd, imm=displacement)
        if displacement % WORD_SIZE:
            raise ISAError("jump displacement is not word-aligned")

    # Декодирование инструкций формата U
    elif fmt is Format.UPPER:
        if word & 0xFF:
            raise ISAError("nonzero reserved bits in LUI")
        instr = Instruction(opcode, rd=rd, imm=(word >> 8) & 0x3FFF)

    else:
        raise ISAError(f"unsupported instruction format: {fmt}")

    _validate_unused(instr)
    return instr


# Вычисляет адрес перехода для PC-relative инструкции
def branch_target(pc: int, instr: Instruction) -> int:
    if FORMATS[instr.opcode] not in {Format.BRANCH, Format.JUMP}:
        raise ISAError("instruction is not PC-relative")
    return (pc + WORD_SIZE + instr.imm) & WORD_MASK


# Выделяет старшие 14 бит из 32-битного значения
def upper(value: int) -> int:
    return (value & WORD_MASK) >> 18


# Выделяет младшие 18 бит из значения
def lower(value: int) -> int:
    return value & 0x3_FFFF


# Разделяет 32-битное значение на старшую и младшую части
def split_address(value: int) -> tuple[int, int]:
    if not 0 <= value <= WORD_MASK:
        raise ISAError(f"32-bit value out of range: {value}")
    return upper(value), lower(value)


# Преобразует объект инструкции в текстовую ассемблерную запись
def disassemble(instr: Instruction, address: int = 0) -> str:
    op = instr.opcode
    rd, rs1, rs2 = REGISTERS[instr.rd], REGISTERS[instr.rs1], REGISTERS[instr.rs2]

    if op in {Opcode.NOP, Opcode.RET, Opcode.IRET, Opcode.HALT}:
        operands = ""
    elif op in {
        Opcode.ADD,
        Opcode.SUB,
        Opcode.MUL,
        Opcode.DIV,
        Opcode.AND,
        Opcode.OR,
        Opcode.XOR,
        Opcode.SHL,
        Opcode.SHR,
        Opcode.SLT,
        Opcode.SLTU,
    }:
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


# Преобразует инструкцию в последовательность из четырёх байтов
def instruction_to_bytes(instr: Instruction) -> bytes:
    return encode(instr).to_bytes(WORD_SIZE, "little")


# Преобразует четыре байта машинного кода обратно в инструкцию
def instruction_from_bytes(data: bytes) -> Instruction:
    if len(data) != WORD_SIZE:
        raise ISAError(f"instruction must be exactly {WORD_SIZE} bytes")
    return decode(int.from_bytes(data, "little"))


# Последовательно перебирает инструкции, содержащиеся в бинарном образе
def iter_instructions(
    data: bytes,
    start_address: int = 0,
) -> Iterator[tuple[int, Instruction]]:
    if len(data) % WORD_SIZE:
        raise ISAError("instruction memory image size is not a multiple of 4")
    for offset in range(0, len(data), WORD_SIZE):
        word = int.from_bytes(data[offset : offset + WORD_SIZE], "little")
        yield start_address + offset, decode(word)
