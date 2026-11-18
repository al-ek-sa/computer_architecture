# ISA — Instruction Set Architecture

## 1. Общая характеристика

CSA4 — 32-битный RISC-процессор с Гарвардской организацией памяти. Инструкции имеют фиксированную длину 32 бита (4 байта). Opcode занимает 6 старших бит `[31:26]`; остальные поля кодируют регистры, непосредственные значения, смещения или резервные биты.

| Характеристика | Значение |
|---|---|
| Архитектура | RISC |
| Разрядность | 32 бита |
| Регистры общего назначения | 16 × 32 бита |
| Длина инструкции | 32 бита |
| Организация памяти | Гарвардская |
| Порядок байтов | Little-endian |
| Адресация данных | Побайтная |
| IMEM | 2^16 |
| DMEM модели | 2^32 |
| Ввод-вывод | Memory-Mapped I/O |
| Входные события | Прерывания |

## 2. Форматы инструкций

Opcode во всех форматах расположен в `[31:26]`.

### R — регистровый

```text
31:26 opcode | 25:22 rd | 21:18 rs1 | 17:14 rs2 | 13:0 reserved
```
Reserved-биты должны быть нулевыми.

### I — immediate

```text
31:26 opcode | 25:22 rd | 21:18 rs1 | 17:0 imm
```

### S — store

```text
31:26 opcode | 25:22 base | 21:18 rs2 | 17:0 offset
```

### B — branch

```text
31:26 opcode | 25:22 rs1 | 21:18 rs2 | 17:0 displacement
```

### U — upper immediate

```text
31:26 opcode | 25:22 rd | 21:8 imm14 | 7:0 reserved
```

### J — jump

```text
31:26 opcode | 25:22 rd | 21:0 displacement
```

## 3. Opcode и система команд

### 3.1 Арифметика и логика

| Opcode | Инструкция | Формат | Описание |
|---:|---|---|---|
| 0x00 | NOP | R | Нет операции |
| 0x01 | ADD | R | Сложение |
| 0x02 | SUB | R | Вычитание |
| 0x03 | MUL | R | Умножение |
| 0x04 | DIV | R | Signed деление |
| 0x05 | AND | R | Побитовое И |
| 0x06 | OR | R | Побитовое ИЛИ |
| 0x07 | XOR | R | XOR |
| 0x08 | NOT | R | Побитовое отрицание |
| 0x09 | SHL | R | Логический сдвиг влево |
| 0x0A | SHR | R | Логический сдвиг вправо |
| 0x0B–0x0F | RESERVED | — | Зарезервировано |

### 3.2 Immediate и память

| Opcode | Инструкция | Формат | Описание |
|---:|---|---|---|
| 0x10 | ADDI | I | Сложение с immediate |
| 0x11 | MOVI | I | Загрузка immediate |
| 0x12 | LUI | U | Загрузка верхней части |
| 0x13 | ORI | I | OR с immediate |
| 0x14 | LOAD | I | Загрузка слова |
| 0x15 | LOADB | I | Загрузка байта |
| 0x16 | STORE | S | Запись слова |
| 0x17 | STOREB | S | Запись байта |
| 0x18–0x1F | RESERVED | — | Зарезервировано |

### 3.3 Сравнения и ветвления

| Opcode | Инструкция | Формат | Описание |
|---:|---|---|---|
| 0x20 | BEQ | B | Переход, если равно |
| 0x21 | BNE | B | Переход, если не равно |
| 0x22 | BLT | B | Signed меньше |
| 0x23 | BGE | B | Signed больше или равно |
| 0x24 | SLT | R | Signed сравнение |
| 0x25 | SLTU | R | Unsigned сравнение |
| 0x26–0x2F | RESERVED | — | Зарезервировано |

### 3.4 Управление потоком

| Opcode | Инструкция | Формат | Описание |
|---:|---|---|---|
| 0x30 | JMP | J | Безусловный переход |
| 0x31 | CALL | J | Вызов процедуры |
| 0x32 | RET | R | Возврат |
| 0x33 | IRET | R | Возврат из прерывания |
| 0x34 | HALT | R | Остановка |
| 0x35–0x3F | RESERVED | — | Зарезервировано |

## 4. Регистры

| Регистр | Алиасы | Назначение |
|---|---|---|
| R0 | `zero`, `x0` | Всегда 0; запись игнорируется |
| R1–R13 | `x1`–`x13` | Общего назначения |
| R14 | `sp`, `x14` | Stack Pointer |
| R15 | `ra`, `x15` | Return Address |

R0 жёстко равен нулю. R1–R13 используются для операндов и промежуточных данных. SP указывает на стек; стек растёт вниз. RA хранит адрес возврата; RET использует R15.

Специализированные регистры:

| Регистр | Размер | Назначение |
|---|---:|---|
| PC | 32 бита | Счётчик команд |
| IR | 32 бита | Регистр текущей инструкции |
| EPC | 32 бита | Адрес возврата после прерывания |
| AR | 32 бита | Регистр адреса памяти |

Они не входят в набор R0–R15 и не адресуются обычными инструкциями.

## 5. Семантика инструкций

Обозначения: `A` — rs1, `B` — rs2, `rd` — регистр результата. Результаты записываются с ограничением 32 бит.

| Инструкция | Синтаксис | Операция |
|---|---|---|
| NOP | `NOP` | Ничего не меняет |
| ADD | `ADD rd, rs1, rs2` | `rd = A + B` |
| SUB | `SUB rd, rs1, rs2` | `rd = A - B` |
| MUL | `MUL rd, rs1, rs2` | `rd = A * B` |
| DIV | `DIV rd, rs1, rs2` | Signed A/B, округление к нулю |
| AND | `AND rd, rs1, rs2` | `rd = A & B` |
| OR | `OR rd, rs1, rs2` | `rd = A \| B` |
| XOR | `XOR rd, rs1, rs2` | `rd = A ^ B` |
| NOT | `NOT rd, rs1` | `rd = ~A` |
| SHL | `SHL rd, rs1, rs2` | `rd = A << (B & 31)` |
| SHR | `SHR rd, rs1, rs2` | Логический `A >> (B & 31)` |
| SLT | `SLT rd, rs1, rs2` | 1, если signed A < B, иначе 0 |
| SLTU | `SLTU rd, rs1, rs2` | 1, если unsigned A < B, иначе 0 |
| ADDI | `ADDI rd, rs1, imm` | `rd = A + sign_extend(imm)` |
| MOVI | `MOVI rd, imm` | `rd = sign_extend(imm)` |
| ORI | `ORI rd, rs1, imm` | `rd = A \| zero_extend(imm)` |
| LUI | `LUI rd, imm` | `rd = imm << 18` |
| LOAD | `LOAD rd, offset(base)` | Загрузить 32-битное слово |
| LOADB | `LOADB rd, offset(base)` | Загрузить байт без знакового расширения |
| STORE | `STORE rs2, offset(base)` | Записать 32-битное слово |
| STOREB | `STOREB rs2, offset(base)` | Записать младшие 8 бит |
| BEQ | `BEQ rs1, rs2, label` | Перейти при A == B |
| BNE | `BNE rs1, rs2, label` | Перейти при A != B |
| BLT | `BLT rs1, rs2, label` | Перейти при signed A < B |
| BGE | `BGE rs1, rs2, label` | Перейти при signed A >= B |
| JMP | `JMP label` | PC-relative переход |
| CALL | `CALL rd, label` | rd = PC+4; перейти |
| RET | `RET` | PC = R15 |
| IRET | `IRET` | PC = EPC; завершить обработчик |
| HALT | `HALT` | Остановить процессор |

DIV при делении на ноль вызывает ошибку исполнения. SHR — логический сдвиг с заполнением нулями.

## 7. MMIO

| Адрес | Имя | Доступ | Назначение |
|---:|---|---|---|
| 0x0 | INPUT_DATA | Read | Получить байт; чтение освобождает буфер |
| 0x4 | OUTPUT_DATA | Write | Вывести младший байт |
| 0x8 | CYCLE_COUNTER | Read | Текущий цикл |

## 8. Векторы и прерывания

| Адрес | Назначение |
|---:|---|
| 0x0000 | Reset vector |
| 0x0004 | Input interrupt vector |
| 0x0008 | Reserved |
| 0x000C | Начало текста |

## 9. Кеш

Кеш применяется к обычным обращениям к DMEM; MMIO bypass.

| Параметр | Значение |
|---|---:|
| Line size | 16 байт |
| Lines | 16 |
| Hit latency | 1 цикл |
| Miss latency | 10 циклов |
| MMIO | Обход кеша |

## 11. Синтаксис ассемблера (EBNF)

### 11.1. Общая структура и лексика

```ebnf
<program> ::= { <line> }
<line> ::= [ <label> ] [ <statement> ] [ <comment> ]
<label> ::= <identifier> ":"
<comment> ::= ";" { <character> }

<identifier> ::= <id-start> { <id-char> }
<id-start> ::= <letter> | "_" | "." | "$"
<id-char> ::= <letter> | <digit> | "_" | "." | "$"
```

### 11.2. Регистры

```ebnf
<register> ::= "R0" | "R1" | "R2" | "R3" | "R4" | "R5" | "R6" | "R7"
             | "R8" | "R9" | "R10" | "R11" | "R12" | "R13" | "R14" | "R15"
             | "x0" | "x1" | "x2" | "x3" | "x4" | "x5" | "x6" | "x7"
             | "x8" | "x9" | "x10" | "x11" | "x12" | "x13" | "x14" | "x15"
             | "zero" | "sp" | "ra"
```

### 11.3. Значения

```ebnf
<value> ::= <number> | <character-literal> | <symbol> | <modifier>
<number> ::= <decimal> | <hex> | <binary> | <octal>
<decimal> ::= [ "-" ] <digit> { <digit> }
<hex> ::= "0x" <hex-digit> { <hex-digit> }
<binary> ::= "0b" <binary-digit> { <binary-digit> }
<octal> ::= "0o" <octal-digit> { <octal-digit> }
<symbol> ::= <identifier>
<modifier> ::= "%hi(" <identifier> ")" | "%lo(" <identifier>"

<character-literal> ::= "'" <character> "'" | "'" <escape> "'"
<escape> ::= "\\n" | "\\t" | "\\r" | "\\0" | "\\\\" | "\\\"" | "\\'"
```

### 11.4. Memory operand

```ebnf
<memory-operand> ::= [ <offset> ] "(" <register> ")"
<offset> ::= <value>
```

### 11.5. Инструкции

```ebnf
<instruction> ::= <r-instruction> | <i-instruction> | <s-instruction>
                | <b-instruction> | <u-instruction> | <j-instruction>

<r-instruction> ::= <three-reg> | <two-reg> | <no-operand>
<three-reg> ::= ("ADD" | "SUB" | "MUL" | "DIV" | "AND" | "OR" | "XOR"
                | "SHL" | "SHR" | "SLT" | "SLTU")
                 <register> "," <register> "," <register>
<two-reg> ::= "NOT" <register> "," <register>
<no-operand> ::= "NOP" | "RET" | "IRET" | "HALT"

<i-instruction> ::= ("ADDI" | "ORI") <register> "," <register> "," <value>
                  | "MOVI" <register> "," <value>
                  | ("LOAD" | "LOADB") <register> "," <memory-operand>

<s-instruction> ::= ("STORE" | "STOREB") <register> "," <memory-operand>

<b-instruction> ::= ("BEQ" | "BNE" | "BLT" | "BGE")
                    <register> "," <register> "," <label-reference>

<u-instruction> ::= "LUI" <register> "," <value>

<j-instruction> ::= "JMP" <label-reference>
                  | "CALL" <register> "," <label-reference>
```

### 11.6. Псевдоинструкции

```ebnf
<pseudo> ::= "J" <label-reference>
            | "CALL" <label-reference>
            | "MV" <register> "," <register>
            | "BEQZ" <register> "," <label-reference>
            | "BNEZ" <register> "," <label-reference>
            | "LI" <register> "," <value>
            | "LA" <register> "," <value>
```

Раскрытие:

| Псевдо | Реальная последовательность |
|---|---|
| J label | JMP label |
| CALL label | CALL R15, label |
| MV rd, rs | ADDI rd, rs, 0 |
| BEQZ rs, label | BEQ rs, R0, label |
| BNEZ rs, label | BNE rs, R0, label |
| LI rd, value | LUI + ORI |
| LA rd, symbol | LUI %hi(symbol) + ORI %lo(symbol) |

### 11.7. Директивы

```ebnf
<directive> ::= ".text" | ".rodata" | ".data" | ".bss"
              | ".org" <constant>
              | ".equ" <identifier> "," <constant>
              | (".global" | ".globl") <symbol-list>
              | ".extern" <symbol-list>
              | ".vector" "INPUT" "," <identifier>
              | ".interrupt" <identifier>
              | ".byte" <byte-list>
              | (".ascii" | ".asciz" | ".string") <string-list>
              | ".word" <value-list>
              | (".space" | ".zero") <constant>
              | ".align" <constant>

<symbol-list> ::= <identifier> { "," <identifier> }
<byte-list> ::= <byte-value> { "," <byte-value> }
<byte-value> ::= <constant> | <string-literal>
<string-list> ::= <string-literal> { "," <string-literal> }
<value-list> ::= <value> { "," <value> }
<string-literal> ::= '"' { <string-character> } '"'
```

### 11.8. Макросы и условная сборка

```ebnf
<macro> ::= ".macro" <identifier> [ <parameters> ]
            <macro-body> ".endm"
<parameters> ::= <identifier> { "," <identifier> }
<macro-body> ::= { <line> }

<conditional> ::= ".if" <condition> <body> [ ".else" <body> ] ".endif"
                | ".ifdef" <identifier> <body> ".endif"
                | ".ifndef" <identifier> <body> ".endif"
```
