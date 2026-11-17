.text
.global _start
.extern relocated_function

_start:
    movi r1, 40
    call relocated_function
    halt
