.text
.global _start
.extern helper

_start:
    movi r1, 40
    call helper
    ; helper возвращает результат в r2.
    halt
