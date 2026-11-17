.text
.global _start
.vector INPUT, input_handler

_start:
    la r4, name_buffer
    movi r1, 4096
    call print_prompt
wait:
    jmp wait

input_handler:
    loadb r2, 0(zero)
    beq r2, zero, finish_input
    movi r5, 10
    beq r2, r5, finish_input
    storeb r2, 0(r4)
    addi r4, r4, 1
    storeb r2, 4(zero)
    iret

finish_input:
    movi r2, 10
    storeb r2, 4(zero)
    movi r2, 72
    storeb r2, 4(zero)
    movi r2, 101
    storeb r2, 4(zero)
    movi r2, 108
    storeb r2, 4(zero)
    storeb r2, 4(zero)
    movi r2, 111
    storeb r2, 4(zero)
    movi r2, 44
    storeb r2, 4(zero)
    movi r2, 32
    storeb r2, 4(zero)
    la r4, name_buffer
print_name:
    loadb r2, 0(r4)
    beq r2, zero, end_message
    storeb r2, 4(zero)
    addi r4, r4, 1
    jmp print_name
end_message:
    movi r2, 33
    storeb r2, 4(zero)
    movi r2, 10
    storeb r2, 4(zero)
    halt

print_prompt:
    movi r2, 87
    storeb r2, 4(zero)
    movi r2, 104
    storeb r2, 4(zero)
    movi r2, 97
    storeb r2, 4(zero)
    movi r2, 116
    storeb r2, 4(zero)
    movi r2, 32
    storeb r2, 4(zero)
    movi r2, 105
    storeb r2, 4(zero)
    movi r2, 115
    storeb r2, 4(zero)
    movi r2, 32
    storeb r2, 4(zero)
    movi r2, 121
    storeb r2, 4(zero)
    movi r2, 111
    storeb r2, 4(zero)
    movi r2, 117
    storeb r2, 4(zero)
    movi r2, 114
    storeb r2, 4(zero)
    movi r2, 32
    storeb r2, 4(zero)
    movi r2, 110
    storeb r2, 4(zero)
    movi r2, 97
    storeb r2, 4(zero)
    movi r2, 109
    storeb r2, 4(zero)
    movi r2, 101
    storeb r2, 4(zero)
    movi r2, 63
    storeb r2, 4(zero)
    movi r2, 10
    storeb r2, 4(zero)
    ret
.bss
name_buffer:
    .space 128
