.text
.global _start

_start:
    movi r1, 7
    movi r2, 0
loop:
    beq r1, zero, done
    movi r3, 1
    beq r1, r3, done
    movi r6, 1
    and r4, r1, r6
    beq r4, zero, even
    ; odd: n = 3*n + 1
    add r5, r1, r1
    add r5, r5, r1
    addi r1, r5, 1
    jmp count
even:
    shr r1, r1, r3
count:
    addi r2, r2, 1
    jmp loop
done:
    halt
