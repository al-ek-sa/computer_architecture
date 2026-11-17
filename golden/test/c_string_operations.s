.text
.global _start

_start:
    movi r1, 4096
    movi r3, 12288
copy_loop:
    loadb r2, 0(r1)
    storeb r2, 0(r3)
    beq r2, zero, print_init
    addi r1, r1, 1
    addi r3, r3, 1
    jmp copy_loop
print_init:
    movi r3, 12288
print_loop:
    loadb r2, 0(r3)
    beq r2, zero, done
    storeb r2, 4(zero)
    addi r3, r3, 1
    jmp print_loop
done:
    halt
.rodata
message:
    .byte 67, 83, 65, 52, 32, 116, 101, 115, 116, 10, 0
.bss
copy_buffer:
    .space 64
