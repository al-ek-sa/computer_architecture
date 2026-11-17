.text
.global _start
.vector INPUT, input_handler

_start:
    movi r2, 0
wait:
    jmp wait

input_handler:
    loadb r3, 0(zero)
    beq r3, zero, finish
    addi r2, r2, 1
    storeb r3, 4(zero)
    iret

finish:
    halt
