from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from app.services.pdf_text import coalesce_pdf_text_runs


def _pdf(
    content: bytes,
    *,
    subtype="/Type0",
    encoding="/Identity-H",
    default=1000,
    fractional_width=False,
):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    fonts = DictionaryObject()
    for name, widths in (
        ("/F1", [65, [600, 450, 650], 95, 96, 550]),
        ("/F2", [65, [900, 550, 500], 95, 96, 800]),
    ):
        descendant = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/CIDFontType2"),
                NameObject("/BaseFont"): NameObject("/TestFont"),
                NameObject("/CIDSystemInfo"): DictionaryObject(
                    {
                        NameObject("/Registry"): TextStringObject("Adobe"),
                        NameObject("/Ordering"): TextStringObject("Identity"),
                        NameObject("/Supplement"): NumberObject(0),
                    }
                ),
                NameObject("/W"): ArrayObject(
                    ArrayObject(NumberObject(item) for item in value)
                    if isinstance(value, list)
                    else NumberObject(value)
                    for value in widths
                ),
            }
        )
        if default is not None:
            descendant[NameObject("/DW")] = FloatObject(default)
        if fractional_width:
            descendant["/W"][1][0] = FloatObject(600.25)
        cmap = DecodedStreamObject()
        cmap.set_data(
            b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
            b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) "
            b"/Supplement 0 >> def /CMapName /Test def /CMapType 2 def\n"
            b"1 begincodespacerange <0000> <ffff> endcodespacerange\n"
            b"1 beginbfrange <0000> <007f> <0000> endbfrange\n"
            b"endcmap CMapName currentdict /CMap defineresource pop end end"
        )
        fonts[NameObject(name)] = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject(subtype),
                NameObject("/BaseFont"): NameObject("/TestFont"),
                NameObject("/Encoding"): NameObject(encoding),
                NameObject("/DescendantFonts"): ArrayObject([descendant]),
                NameObject("/ToUnicode"): writer._add_object(cmap),
            }
        )
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): fonts})
    stream = DecodedStreamObject()
    stream.set_data(content)
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_metadata({"/Title": "Resume copy test", "/Author": "Avery Chen"})
    writer.add_annotation(
        0,
        {
            "/Type": "/Annot",
            "/Subtype": "/Link",
            "/Rect": [20, 20, 180, 40],
            "/A": {"/S": "/URI", "/URI": "https://example.com/avery_chen"},
        },
    )
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _operations(pdf_bytes):
    return PdfReader(BytesIO(pdf_bytes)).pages[0].get_contents().operations


def _raw(value):
    return bytes(value) if isinstance(value, bytes) else value.original_bytes


def _glyph_positions(pdf_bytes, default_width=1000):
    widths = {
        "/F1": {65: 600, 66: 450, 67: 650, 95: 550, 96: 550},
        "/F2": {65: 900, 66: 550, 67: 500, 95: 800, 96: 800},
    }
    matrix = line = (1, 0, 0, 1, 0, 0)
    font, size = "/F1", 0
    result = []

    def translate(source, x, y=0):
        a, b, c, d, e, f = source
        return a, b, c, d, e + a * x + c * y, f + b * x + d * y

    for operands, operator in _operations(pdf_bytes):
        if operator == b"BT":
            matrix = line = (1, 0, 0, 1, 0, 0)
        elif operator == b"Tf":
            font, size = str(operands[0]), float(operands[1])
        elif operator == b"Tm":
            matrix = line = tuple(float(value) for value in operands)
        elif operator == b"Td":
            matrix = line = translate(line, *map(float, operands))
        elif operator in (b"Tj", b"TJ"):
            values = operands if operator == b"Tj" else operands[0]
            for value in values:
                if isinstance(value, (int, float)):
                    matrix = translate(matrix, -float(value) * size / 1000)
                    continue
                raw = _raw(value)
                for index in range(0, len(raw), 2):
                    cid = int.from_bytes(raw[index : index + 2], "big")
                    result.append((font, cid, matrix[4], matrix[5]))
                    matrix = translate(
                        matrix, widths[font].get(cid, default_width) * size / 1000
                    )
    return result


def _assert_same_positions(before, after, default_width=1000):
    expected = _glyph_positions(before, default_width)
    actual = _glyph_positions(after, default_width)
    assert [(font, cid) for font, cid, _, _ in actual] == [
        (font, cid) for font, cid, _, _ in expected
    ]
    for original, rewritten in zip(expected, actual, strict=True):
        assert rewritten[2:] == pytest.approx(original[2:], abs=1e-7)


@pytest.mark.parametrize("default", [None, 750, 1000])
@pytest.mark.parametrize("matrix", [b"1 0 0 1", b"0.8 0.3 -0.2 1.1"])
def test_coalescing_preserves_cid_positions_with_array_range_and_default_widths(
    default, matrix
):
    before = _pdf(
        b"BT /F1 10 Tf " + matrix + b" 30 150 Tm 2 0 Td 3 0 Td <0041> Tj <005f0042> Tj "
        b"19 0 Td <00430060> Tj 8 0 Td <0044> Tj ET",
        default=default,
    )

    after = coalesce_pdf_text_runs(before)

    _assert_same_positions(before, after, default or 1000)
    assert [cid for _, cid, _, _ in _glyph_positions(after)] == [65, 95, 66, 67, 96, 68]
    assert [operator for _, operator in _operations(after)].count(b"TJ") == 1
    if matrix == b"1 0 0 1":
        assert [x for _, _, x, _ in _glyph_positions(after)] == pytest.approx(
            [35, 41, 46.5, 54, 60.5, 62]
        )


def test_underscore_line_remains_one_text_run_without_losing_content():
    phrase = "EXPERIENCE_1_SENTINEL"
    drawings = []
    for index, char in enumerate(phrase):
        if index:
            width = {"C": 650, "_": 550}.get(phrase[index - 1], 600)
            drawings.append(f"{width * 12 / 1000} 0 Td".encode())
        drawings.append(f"<{ord(char):04x}> Tj".encode())
    before = _pdf(
        b"BT /F1 12 Tf 1 0 0 1 40 700 Tm " + b" ".join(drawings) + b" ET",
        default=600,
    )

    after = coalesce_pdf_text_runs(before)

    _assert_same_positions(before, after, 600)
    text_runs = [operands[0] for operands, op in _operations(after) if op == b"TJ"]
    assert len(text_runs) == 1
    assert (
        b"".join(
            _raw(value) for value in text_runs[0] if not isinstance(value, (int, float))
        ).decode("utf-16-be")
        == phrase
    )
    assert phrase in PdfReader(BytesIO(after)).pages[0].extract_text()


def test_multiple_text_objects_keep_each_font_and_preserve_links_and_metadata():
    before = _pdf(
        b"BT /F1 10 Tf 1 0 0 1 40 700 Tm <0041> Tj 6 0 Td <005f> Tj ET "
        b"0 0 1 rg 10 10 30 40 re f "
        b"BT /F2 18 Tf 1 0 0 1 70 650 Tm <0042> Tj <005f0043> Tj ET"
    )

    after = coalesce_pdf_text_runs(before)

    _assert_same_positions(before, after)
    assert [op for _, op in _operations(after)].count(b"TJ") == 2
    assert [operands for operands, op in _operations(after) if op == b"Tf"] == [
        ["/F1", 10],
        ["/F2", 18],
    ]
    original, rewritten = PdfReader(BytesIO(before)), PdfReader(BytesIO(after))
    assert rewritten.metadata == original.metadata
    assert rewritten.pages[0].mediabox == original.pages[0].mediabox
    for reader in (original, rewritten):
        link = reader.pages[0]["/Annots"][0].get_object()
        assert link["/A"]["/URI"] == "https://example.com/avery_chen"
        assert list(link["/Rect"]) == [20, 20, 180, 40]
    assert [item for item in _operations(after) if item[1] in (b"rg", b"re", b"f")] == [
        item for item in _operations(before) if item[1] in (b"rg", b"re", b"f")
    ]


@pytest.mark.parametrize(
    "content",
    [
        b"BT /F1 12 Tf 1 0 0 1 40 700 Tm <0041> Tj 8 -14 Td <0042> Tj ET",
        b"1 Tc BT /F1 12 Tf 1 0 0 1 40 700 Tm <0041> Tj <0042> Tj ET",
        b"2 Tw BT /F1 12 Tf 1 0 0 1 40 700 Tm <0041> Tj <0042> Tj ET",
        b"80 Tz BT /F1 12 Tf 1 0 0 1 40 700 Tm <0041> Tj <0042> Tj ET",
        b"BT /F1 12 Tf 1 0 0 1 40 700 Tm 1 Tc <0041> Tj <0042> Tj ET",
        b"BT /F1 12 Tf 1 0 0 1 40 700 Tm <0041> Tj /F2 12 Tf <0042> Tj ET",
        b"BT /F1 12 Tf 1 0 0 1 40 700 Tm <0041> Tj [<0042>] TJ ET",
        b"BT /F1 12 Tf 1 0 0 1 40 700 Tm <0041> Tj T* <0042> Tj ET",
        b"BT /F1 12 Tf 1 0 0 1 40 700 Tm <0041> Tj 1 0 0 rg <0042> Tj ET",
        b"BT /F1 12 Tf 1 0 0 1 40 700 Tm <0041> Tj <42> Tj ET",
    ],
)
def test_unsupported_text_layouts_are_preserved(content):
    before = _pdf(content)

    after = coalesce_pdf_text_runs(before)

    assert _operations(after) == _operations(before)


@pytest.mark.parametrize(
    ("subtype", "encoding"), [("/Type1", "/Identity-H"), ("/Type0", "/Identity-V")]
)
def test_fonts_outside_horizontal_cid_encoding_are_preserved(subtype, encoding):
    before = _pdf(
        b"BT /F1 12 Tf 1 0 0 1 40 700 Tm <0041> Tj <0042> Tj ET",
        subtype=subtype,
        encoding=encoding,
    )

    assert _operations(coalesce_pdf_text_runs(before)) == _operations(before)


@pytest.mark.parametrize(
    ("fractional_width", "default"), [(True, 1000), (False, 999.75)]
)
def test_fractional_font_metrics_keep_original_reader_positioning(
    fractional_width, default
):
    before = _pdf(
        b"BT /F1 12 Tf 1 0 0 1 40 700 Tm <0041> Tj 7.2 0 Td <0042> Tj ET",
        fractional_width=fractional_width,
        default=default,
    )

    assert _operations(coalesce_pdf_text_runs(before)) == _operations(before)


def test_restored_graphics_state_allows_default_spacing_text_to_coalesce():
    spaced = b"BT /F1 12 Tf 1 0 0 1 40 700 Tm <0041> Tj <0042> Tj ET"
    ordinary = b"BT /F1 12 Tf 1 0 0 1 40 650 Tm <0041> Tj <0042> Tj ET"
    before = _pdf(b"q 2 Tc " + spaced + b" Q " + ordinary)

    operations = _operations(coalesce_pdf_text_runs(before))

    assert [op for _, op in operations].count(b"Tj") == 2
    assert [op for _, op in operations].count(b"TJ") == 1
