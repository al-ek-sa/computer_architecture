.text
.global _start

_start:
    movi r2, 50
    storeb r2, 4(zero)
    movi r2, 51
    storeb r2, 4(zero)
    movi r2, 52
    storeb r2, 4(zero)
    movi r2, 42
    storeb r2, 4(zero)
    movi r2, 43
    storeb r2, 4(zero)
    movi r2, 10
    storeb r2, 4(zero)
    halt
