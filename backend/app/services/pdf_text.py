from __future__ import annotations

from io import BytesIO
from typing import Any, cast

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    ByteStringObject,
    DictionaryObject,
    FloatObject,
)

type Operation = tuple[Any, bytes]


def _cid_widths(font: DictionaryObject) -> tuple[dict[int, float], float]:
    descendants = cast(ArrayObject, font["/DescendantFonts"])
    descendant = cast(DictionaryObject, descendants[0].get_object())
    values = descendant.get("/W", [])
    widths: dict[int, float] = {}
    index = 0
    while index < len(values):
        start = int(values[index])
        entry = values[index + 1]
        if isinstance(entry, ArrayObject):
            widths.update(
                (start + offset, float(width)) for offset, width in enumerate(entry)
            )
            index += 2
        else:
            width = float(values[index + 2])
            widths.update((cid, width) for cid in range(start, int(entry) + 1))
            index += 3
    return widths, float(descendant.get("/DW", 1000))


def _coalesce_text_object(
    operations: list[Operation], fonts: DictionaryObject
) -> list[Operation]:
    if (
        len(operations) < 3
        or operations[0][1] != b"Tf"
        or operations[1][1] != b"Tm"
        or any(operator not in (b"Tj", b"Td") for _, operator in operations[2:])
        or sum(operator == b"Tj" for _, operator in operations[2:]) < 2
    ):
        return operations

    font_name, font_size = operations[0][0]
    font_size = float(font_size)
    font = cast(DictionaryObject, fonts[font_name])
    if font.get("/Subtype") != "/Type0" or font.get("/Encoding") != "/Identity-H":
        return operations
    if font_size <= 0:
        return operations

    widths, default_width = _cid_widths(font)
    if not default_width.is_integer() or any(
        not width.is_integer() for width in widths.values()
    ):
        return operations
    segments = ArrayObject()
    advance = 0.0
    for operands, operator in operations[2:]:
        if operator == b"Td":
            if float(operands[1]) != 0:
                return operations
            segments.append(
                FloatObject(advance - float(operands[0]) * 1000 / font_size)
            )
            advance = 0.0
        else:
            value = operands[0]
            raw = bytes(value) if isinstance(value, bytes) else value.original_bytes
            if len(raw) % 2:
                return operations
            segments.append(ByteStringObject(raw))
            advance += sum(
                widths.get(int.from_bytes(raw[index : index + 2], "big"), default_width)
                for index in range(0, len(raw), 2)
            )

    return [*operations[:2], ([segments], b"TJ")]


def coalesce_pdf_text_runs(pdf_bytes: bytes) -> bytes:
    """Combine horizontal integer-width CID text runs, preserving glyph positions."""

    writer = PdfWriter(clone_from=BytesIO(pdf_bytes))
    for page in writer.pages:
        contents = page.get_contents()
        if contents is None:
            continue
        resources = cast(DictionaryObject, page["/Resources"])
        fonts = (
            cast(DictionaryObject, resources["/Font"])
            if "/Font" in resources
            else DictionaryObject()
        )
        output: list[Operation] = []
        block: list[Operation] | None = None
        spacing = {b"Tc": 0.0, b"Tw": 0.0, b"Tz": 100.0}
        stack: list[dict[bytes, float]] = []
        default_spacing = True
        for operands, operator in contents.operations:
            if operator == b"q":
                stack.append(spacing.copy())
            elif operator == b"Q":
                spacing = stack.pop()
            elif operator in spacing:
                spacing[operator] = float(operands[0])

            if operator == b"BT":
                block = []
                default_spacing = spacing == {b"Tc": 0.0, b"Tw": 0.0, b"Tz": 100.0}
                output.append((operands, operator))
            elif operator == b"ET" and block is not None:
                output.extend(
                    _coalesce_text_object(block, fonts) if default_spacing else block
                )
                output.append((operands, operator))
                block = None
            elif block is not None:
                block.append((operands, operator))
            else:
                output.append((operands, operator))
        contents.operations = output
        page.replace_contents(contents)
        page.compress_content_streams()
    result = BytesIO()
    writer.write(result)
    return result.getvalue()
