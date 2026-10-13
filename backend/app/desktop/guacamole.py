"""The Guacamole wire format: `LEN.value,LEN.value,...;` where `LEN` counts Unicode characters."""

from typing import NamedTuple

DEFAULT_MAX_INSTRUCTION_CHARS = 262_144
MAX_LENGTH_DIGITS = 7
INTERNAL_OPCODE = ""

ELEMENT_SEPARATOR = ","
INSTRUCTION_TERMINATOR = ";"
LENGTH_TERMINATOR = "."


class ProtocolError(ValueError):
    """The peer sent text that is not a Guacamole instruction."""


class Instruction(NamedTuple):
    opcode: str
    args: tuple[str, ...]


def encode(opcode: str, *args: str) -> str:
    elements = (opcode, *args)
    return (
        ELEMENT_SEPARATOR.join(
            f"{len(element)}{LENGTH_TERMINATOR}{element}" for element in elements
        )
        + INSTRUCTION_TERMINATOR
    )


class InstructionDecoder:
    """Turns arbitrarily cut text into whole instructions. After a `ProtocolError` it is spent."""

    def __init__(self, max_instruction_chars: int = DEFAULT_MAX_INSTRUCTION_CHARS) -> None:
        self._max_instruction_chars = max_instruction_chars
        self._pending = ""
        self._position = 0
        self._elements: list[str] = []
        self._value_length: int | None = None

    def feed(self, text: str) -> list[Instruction]:
        self._pending += text
        instructions: list[Instruction] = []
        while (instruction := self._next_instruction()) is not None:
            instructions.append(instruction)
        return instructions

    def _next_instruction(self) -> Instruction | None:
        while True:
            if self._value_length is None:
                self._value_length = self._read_length()
            if self._value_length is None:
                return None
            end_of_value = self._position + self._value_length
            if len(self._pending) <= end_of_value:
                return None
            self._value_length = None
            self._elements.append(self._pending[self._position : end_of_value])
            terminator = self._pending[end_of_value]
            self._position = end_of_value + 1
            if terminator == INSTRUCTION_TERMINATOR:
                return self._finish_instruction()
            if terminator != ELEMENT_SEPARATOR:
                raise ProtocolError(f"expected ',' or ';' after an element, got {terminator!r}")

    def _read_length(self) -> int | None:
        """The length of the next element, leaving the position at its first character."""
        digits_end = self._pending.find(LENGTH_TERMINATOR, self._position)
        if digits_end == -1:
            digits_end = len(self._pending)
        digits = self._pending[self._position : digits_end]
        if not (digits.isascii() and (digits.isdigit() or digits == "")):
            raise ProtocolError(f"element length is not a number: {digits[:20]!r}")
        if len(digits) > MAX_LENGTH_DIGITS:
            raise ProtocolError("element length has too many digits")
        if digits_end == len(self._pending):
            return None
        if not digits:
            raise ProtocolError("element length is missing")
        length = int(digits)
        value_start = digits_end + 1
        # `+ 1` for the separator or terminator that must follow the value.
        if value_start + length + 1 > self._max_instruction_chars:
            raise ProtocolError(f"instruction too long (limit {self._max_instruction_chars})")
        self._position = value_start
        return length

    def _finish_instruction(self) -> Instruction:
        opcode, *args = self._elements
        self._pending = self._pending[self._position :]
        self._position = 0
        self._elements = []
        return Instruction(opcode, tuple(args))
