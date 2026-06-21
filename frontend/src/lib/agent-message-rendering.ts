const MARKDOWN_BLOCK_PATTERN =
  /(^|\n)\s*(#{1,6}\s|[-*+]\s|\d+\.\s|>|```)/;
const MARKDOWN_INLINE_PATTERN =
  /`|[[\]]|(\*\*|__)[^\n]+?\1|(?:^|[\s\u3000])([*_])[^*_\n]+?\2/;

export function isPlainAgentText(text: string) {
  return !MARKDOWN_BLOCK_PATTERN.test(text) && !MARKDOWN_INLINE_PATTERN.test(text);
}
