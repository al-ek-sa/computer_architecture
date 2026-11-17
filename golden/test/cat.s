.text
.global _start
.vector INPUT, input_handler

_start:
wait:
    jmp wait

input_handler:
    loadb r2, 0(zero)
    beq r2, zero, finish
    storeb r2, 4(zero)
    iret

finish:
    halt
