import random

import pytest

from app.desktop.guacamole import (
    Instruction,
    InstructionDecoder,
    ProtocolError,
    encode,
)


def decode_all(text: str, *, chunk_size: int | None = None) -> list[Instruction]:
    decoder = InstructionDecoder()
    if chunk_size is None:
        return decoder.feed(text)
    found: list[Instruction] = []
    for start in range(0, len(text), chunk_size):
        found.extend(decoder.feed(text[start : start + chunk_size]))
    return found


def test_encode_prefixes_every_element_with_its_length() -> None:
    assert encode("select", "vnc") == "6.select,3.vnc;"


def test_encode_an_instruction_without_arguments() -> None:
    assert encode("audio") == "5.audio;"


def test_encode_an_empty_argument_is_a_zero_length_element() -> None:
    assert encode("audio", "") == "5.audio,0.;"


def test_encode_counts_characters_not_bytes() -> None:
    assert encode("clipboard", "zażółć") == "9.clipboard,6.zażółć;"


def test_encode_the_internal_instruction_has_an_empty_opcode() -> None:
    assert encode("", "0123") == "0.,4.0123;"


def test_decode_one_instruction() -> None:
    assert decode_all("4.size,4.1280,3.800,2.96;") == [Instruction("size", ("1280", "800", "96"))]


def test_decode_two_instructions_in_one_chunk() -> None:
    assert decode_all("3.nop;4.sync,2.12;") == [
        Instruction("nop", ()),
        Instruction("sync", ("12",)),
    ]


def test_decode_counts_characters_not_bytes() -> None:
    assert decode_all("9.clipboard,6.zażółć;") == [Instruction("clipboard", ("zażółć",))]


def test_decode_a_value_may_contain_the_separators() -> None:
    assert decode_all("3.key,5.a,b;c;") == [Instruction("key", ("a,b;c",))]


def test_decode_an_empty_opcode_is_the_internal_instruction() -> None:
    assert decode_all("0.,4.ping,1.5;") == [Instruction("", ("ping", "5"))]


def test_decode_empty_arguments() -> None:
    assert decode_all("5.audio,0.;") == [Instruction("audio", ("",))]


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 5, 7])
def test_decode_is_the_same_however_the_text_is_cut(chunk_size: int) -> None:
    text = "".join(
        [
            encode("args", "VERSION_1_5_0", "hostname", "port"),
            encode("clipboard", "zażółć gęślą jaźń"),
            encode("", "ping", "1700000000000"),
            encode("audio", ""),
            encode("blob", "9", "x" * 300),
        ]
    )

    assert decode_all(text, chunk_size=chunk_size) == decode_all(text)


def test_decode_random_cuts_equal_the_whole() -> None:
    generator = random.Random(7)  # noqa: S311 - deterministic test data
    text = "".join(encode("ząb", "ž" * generator.randrange(0, 40), "a,b;") for _ in range(30))
    whole = decode_all(text)
    decoder = InstructionDecoder()
    found: list[Instruction] = []
    position = 0
    while position < len(text):
        step = generator.randrange(1, 17)
        found.extend(decoder.feed(text[position : position + step]))
        position += step

    assert found == whole
    assert len(whole) == 30


def test_decode_waits_when_cut_inside_a_length() -> None:
    decoder = InstructionDecoder()

    assert decoder.feed("4.size,4.12") == []
    assert decoder.feed("80,3.800;") == [Instruction("size", ("1280", "800"))]


def test_decode_waits_when_cut_before_the_dot() -> None:
    decoder = InstructionDecoder()

    assert decoder.feed("12") == []
    assert decoder.feed("3") == []
    assert decoder.feed(".") == []


def test_decode_waits_when_cut_inside_a_value() -> None:
    decoder = InstructionDecoder()

    assert decoder.feed("9.clipboard,6.zaż") == []
    assert decoder.feed("ółć;") == [Instruction("clipboard", ("zażółć",))]


def test_decode_waits_when_cut_before_the_terminator() -> None:
    decoder = InstructionDecoder()

    assert decoder.feed("3.nop") == []
    assert decoder.feed(";") == [Instruction("nop", ())]


def test_decode_yields_the_complete_ones_and_keeps_the_partial_tail() -> None:
    decoder = InstructionDecoder()

    assert decoder.feed("3.nop;4.sync,2.1") == [Instruction("nop", ())]
    assert decoder.feed("2;") == [Instruction("sync", ("12",))]


@pytest.mark.parametrize(
    "text",
    [
        "x.size;",
        ".size;",
        "-1.size;",
        "+4.size;",
        "٤.size;",
        "4.size!",
        "4.sizeX",
        "3.nop,;",
        ";",
        "3.nop;;",
    ],
)
def test_decode_malformed_text_raises_a_clear_error(text: str) -> None:
    with pytest.raises(ProtocolError):
        decode_all(text)


def test_decode_an_error_names_what_was_wrong() -> None:
    with pytest.raises(ProtocolError, match="length"):
        InstructionDecoder().feed("zz.size;")


def test_decode_rejects_a_length_that_could_never_fit() -> None:
    decoder = InstructionDecoder(max_instruction_chars=100)

    with pytest.raises(ProtocolError, match="too long"):
        decoder.feed("1000.")


def test_decode_rejects_an_instruction_that_grows_past_the_limit_across_elements() -> None:
    decoder = InstructionDecoder(max_instruction_chars=20)

    with pytest.raises(ProtocolError, match="too long"):
        decoder.feed("4.blob,10.0123456789,10.0123456789;")


def test_decode_rejects_an_endless_length_without_waiting_for_a_dot() -> None:
    decoder = InstructionDecoder()

    with pytest.raises(ProtocolError, match="length"):
        decoder.feed("1" * 50)


def test_decode_accepts_an_instruction_exactly_at_the_limit() -> None:
    instruction = encode("blob", "1", "x" * 10)
    decoder = InstructionDecoder(max_instruction_chars=len(instruction))

    assert decoder.feed(instruction) == [Instruction("blob", ("1", "x" * 10))]


def test_round_trip_through_encode() -> None:
    instruction = Instruction("img", ("3", "14", "0", "image/png", "0", "0"))

    assert decode_all(encode(instruction.opcode, *instruction.args)) == [instruction]
