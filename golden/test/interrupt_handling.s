.text
.global _start
.vector INPUT, input_handler

_start:
    movi r1, 0
wait:
    jmp wait

input_handler:
    loadb r2, 0(zero)
    beq r2, zero, finish
    addi r1, r1, 1
    storeb r2, 4(zero)
    iret
finish:
    halt
