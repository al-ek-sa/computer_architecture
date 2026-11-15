.text
.global _start
.global input_handler

.vector INPUT, input_handler

_start:
idle:
    JMP idle

input_handler:
    LOADB R1, 0(R0)
    STOREB R1, 4(R0)

    IRET