.text
.global _start

_start:
    movi r1, 4096
print_loop:
    loadb r2, 0(r1)
    beq r2, zero, finish
    storeb r2, 4(zero)
    addi r1, r1, 1
    jmp print_loop
finish:
    halt
.rodata
hello:
    .byte 104, 101, 108, 108, 111, 32, 119, 111, 114, 108, 100, 10, 0
