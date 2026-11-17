.text
.global _start

_start:
    loadb r2, 0(zero)
    beq r2, zero, done
    storeb r2, 4(zero)
done:
    halt
