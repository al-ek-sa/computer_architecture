.text
.global _start

_start:
    movi r1, -1
    movi r2, 1
    movi r3, 2
    movi r4, 0

    add r5, r1, r3
    sltu r6, r5, r1
    add r7, r2, r4
    add r7, r7, r6
    halt
