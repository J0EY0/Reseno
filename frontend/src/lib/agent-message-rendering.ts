const MARKDOWN_BLOCK_PATTERN =
  /(^|\n)\s*(#{1,6}\s|[-*+]\s|\d+\.\s|>|```)/;
const MARKDOWN_INLINE_PATTERN =
  /`|[[\]]|(\*\*|__)[^\n]+?\1|(?:^|[\s\u3000])([*_])[^*_\n]+?\2/;
const AGENT_SOURCE_ID_PATTERN = /^source-[a-z0-9]+(?:-[a-z0-9]+)*$/;
const AGENT_CITATION_TAG_PATTERN = /<\/?citation(?:\s[^<>]*)?>/gi;
const AGENT_CITATION_MARKER_PATTERN = /<\/?citation\b/i;
const AGENT_CITATION_OPEN_PATTERN =
  /^<citation\s+source_ids="[^"]*"\s*>$/i;
const AGENT_CITATION_CLOSE_PATTERN = /^<\/citation\s*>$/i;
const AGENT_CITATION_MARKERS = ["<citation", "</citation"] as const;
const MAX_AGENT_CITATION_SOURCES = 3;

function trailingAgentCitationPrefixLength(text: string) {
  const normalized = text.toLowerCase();
  let matchedLength = 0;

  for (const marker of AGENT_CITATION_MARKERS) {
    const maxLength = Math.min(marker.length, normalized.length);
    for (let length = maxLength; length > matchedLength; length -= 1) {
      if (normalized.endsWith(marker.slice(0, length))) {
        matchedLength = length;
        break;
      }
    }
  }

  return matchedLength;
}

export function getAgentCitationSourceIds(value: unknown) {
  if (typeof value !== "string") {
    return [];
  }

  const sourceIds = value.split(",").map((sourceId) => sourceId.trim());
  if (
    !sourceIds.length ||
    sourceIds.some((sourceId) => !AGENT_SOURCE_ID_PATTERN.test(sourceId))
  ) {
    return [];
  }

  const uniqueSourceIds = [...new Set(sourceIds)];
  return uniqueSourceIds.length <= MAX_AGENT_CITATION_SOURCES
    ? uniqueSourceIds
    : [];
}

export function hasCompleteAgentCitationMarkup(text: string) {
  let depth = 0;
  let cursor = 0;
  let sawCitation = false;

  for (const match of text.matchAll(AGENT_CITATION_TAG_PATTERN)) {
    const index = match.index;
    if (
      index === undefined ||
      AGENT_CITATION_MARKER_PATTERN.test(text.slice(cursor, index))
    ) {
      return false;
    }

    const tag = match[0];
    if (AGENT_CITATION_CLOSE_PATTERN.test(tag)) {
      if (depth !== 1) {
        return false;
      }
      depth = 0;
    } else {
      if (depth !== 0 || !AGENT_CITATION_OPEN_PATTERN.test(tag)) {
        return false;
      }
      depth = 1;
      sawCitation = true;
    }
    cursor = index + tag.length;
  }

  return (
    sawCitation &&
    depth === 0 &&
    !AGENT_CITATION_MARKER_PATTERN.test(text.slice(cursor)) &&
    trailingAgentCitationPrefixLength(text.slice(cursor)) === 0
  );
}

export function hasAgentCitationMarkupCandidate(text: string) {
  return (
    AGENT_CITATION_MARKER_PATTERN.test(text) ||
    trailingAgentCitationPrefixLength(text) > 0
  );
}

export function stripAgentCitationMarkup(text: string) {
  const withoutTags = text.replace(/<\/?citation(?:\s[^>]*)?>?/gi, "");
  const trailingPrefixLength = trailingAgentCitationPrefixLength(withoutTags);
  return trailingPrefixLength
    ? withoutTags.slice(0, -trailingPrefixLength)
    : withoutTags;
}

export function isPlainAgentText(text: string) {
  return !MARKDOWN_BLOCK_PATTERN.test(text) && !MARKDOWN_INLINE_PATTERN.test(text);
}
