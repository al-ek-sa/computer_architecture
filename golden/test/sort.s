.text
.global _start

_start:
    movi r1, 8192
    movi r2, 5
    movi r3, 0
outer:
    bge r3, r2, print_init
    movi r4, 0
    sub r5, r2, r3
    addi r5, r5, -1
inner:
    bge r4, r5, next_outer
    add r6, r1, r4
    loadb r7, 0(r6)
    addi r6, r6, 1
    loadb r8, 0(r6)
    blt r7, r8, no_swap
    beq r7, r8, no_swap
    storeb r8, -1(r6)
    storeb r7, 0(r6)
no_swap:
    addi r4, r4, 1
    jmp inner
next_outer:
    addi r3, r3, 1
    jmp outer
print_init:
    movi r4, 0
print_loop:
    bge r4, r2, done
    add r6, r1, r4
    loadb r7, 0(r6)
    storeb r7, 4(zero)
    movi r8, 32
    storeb r8, 4(zero)
    addi r4, r4, 1
    jmp print_loop
done:
    movi r8, 10
    storeb r8, 4(zero)
    halt
.data
values:
    .byte 5, 3, 1, 4, 2
