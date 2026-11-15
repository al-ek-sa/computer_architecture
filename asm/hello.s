.text
.global _start

_start:
    LI R1, message

print_loop:
    LOADB R2, 0(R1)
    BEQ R2, R0, done

    STOREB R2, 4(R0)
    ADDI R1, R1, 1
    JMP print_loop

done:
    HALT

.rodata
message:
    .asciz "Hello, world!\n"