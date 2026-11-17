.text
.global _start

_start:
    movi r1, 8192
    movi r2, 8
    movi r3, 0
pass1:
    bge r3, r2, reset
    add r4, r3, r3
    add r4, r4, r4
    add r4, r1, r4
    load r5, 0(r4)
    addi r3, r3, 1
    jmp pass1
reset:
    movi r3, 0
pass2:
    bge r3, r2, done
    add r4, r3, r3
    add r4, r4, r4
    add r4, r1, r4
    load r5, 0(r4)
    addi r3, r3, 1
    jmp pass2
done:
    halt
.data
array:
    .word 1, 2, 3, 4, 5, 6, 7, 8
