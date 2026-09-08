import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser

_RICH_TEXT_TAG_PATTERN = re.compile(
    r"</?(?:p|ul|ol|li|br|strong|em|u|sup|sub)(?:\s[^<>]*|/?)>",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class ResumeTextSpan:
    source_start: int
    source_end: int
    text_start: int
    text_end: int


@dataclass(frozen=True)
class ResumeTextProjection:
    text: str
    spans: tuple[ResumeTextSpan, ...]
    script_boundaries: frozenset[int]


class _ResumeTextParser(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.source = source
        self.line_offsets = [0, *(match.end() for match in re.finditer("\n", source))]
        self.parts: list[str] = []
        self.spans: list[ResumeTextSpan] = []
        self.text_length = 0
        self.script_boundaries: set[int] = set()

    def _append_text(self, text: str, source_length: int | None = None) -> None:
        if source_length is not None:
            line, column = self.getpos()
            source_start = self.line_offsets[line - 1] + column
            self.spans.append(ResumeTextSpan(
                source_start, source_start + source_length,
                self.text_length, self.text_length + len(text),
            ))
        self.parts.append(text)
        self.text_length += len(text)

    def handle_data(self, data: str) -> None:
        self._append_text(data, len(data))

    def _append_entity(self, name: str) -> None:
        line, column = self.getpos()
        start = self.line_offsets[line - 1] + column
        end = start + len(name) + 1
        if self.source[end:end + 1] == ";":
            end += 1
        self._append_text(unescape(self.source[start:end]), end - start)

    def handle_entityref(self, name: str) -> None:
        self._append_entity(name)

    def handle_charref(self, name: str) -> None:
        self._append_entity(f"#{name}")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"sup", "sub"}:
            self.script_boundaries.add(self.text_length)
        if tag in {"p", "li", "br", "ul", "ol"}:
            self._append_text("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"sup", "sub"}:
            self.script_boundaries.add(self.text_length)
        if tag in {"p", "li", "ul", "ol"}:
            self._append_text("\n")


def resume_text_projection(value: str) -> ResumeTextProjection | None:
    if not _RICH_TEXT_TAG_PATTERN.search(value):
        return None
    parser = _ResumeTextParser(value)
    parser.feed(value)
    parser.close()
    return ResumeTextProjection(
        "".join(parser.parts), tuple(parser.spans), frozenset(parser.script_boundaries),
    )


def resume_text_content(value: str) -> str:
    projection = resume_text_projection(value)
    return value if projection is None else projection.text.strip()
