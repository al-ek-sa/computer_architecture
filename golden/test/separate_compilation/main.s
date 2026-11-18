.text
.global _start
.extern helper

_start:
    movi r1, 40
    call helper
    halt
