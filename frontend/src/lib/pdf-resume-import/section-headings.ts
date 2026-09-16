import type { TextLine } from "./pdf-text-extraction";
import { median, PDF_IMPORT_PROFILE } from "./parser-config";
import { countTextGraphemes } from "./text-heuristics";

export function createSectionHeadingDetector(
  lines: TextLine[],
  knownHeadingIndexes: Set<number>,
) {
  const bodyLines = lines.filter((_, index) => !knownHeadingIndexes.has(index));
  const bodyFontSize = median(
    bodyLines.map((line) => line.fontSize).filter(Boolean),
  );
  const fonts = new Map<string, number>();
  for (const line of bodyLines) {
    if (line.fontName) {
      fonts.set(
        line.fontName,
        (fonts.get(line.fontName) ?? 0) + countTextGraphemes(line.text),
      );
    }
  }
  const bodyFont = [...fonts].sort((left, right) => right[1] - left[1])[0]?.[0];
  const headingStyles = lines.filter(
    (line, index) =>
      knownHeadingIndexes.has(index) &&
      (line.fontSize > bodyFontSize + sizeTolerance(line.fontSize) ||
        (line.fontName && bodyFont && line.fontName !== bodyFont)),
  );
  const firstHeadingIndex = Math.min(...knownHeadingIndexes);

  return (line: TextLine, index: number) => {
    if (
      countTextGraphemes(line.text) >
        PDF_IMPORT_PROFILE.text.maxGenericSectionHeadingGraphemes ||
      !/\p{L}/u.test(line.text) ||
      /[：:。！？!?；;]|[.]$/u.test(line.text)
    ) {
      return false;
    }
    const matchesHeadingStyle =
      index > firstHeadingIndex &&
      headingStyles.some(
        (heading) =>
          Math.abs(line.fontSize - heading.fontSize) <=
            sizeTolerance(heading.fontSize) &&
          Math.abs(line.x - heading.x) <= heading.fontSize / 2 &&
          (heading.fontSize > bodyFontSize + sizeTolerance(heading.fontSize) ||
            !line.fontName ||
            !heading.fontName ||
            line.fontName === heading.fontName),
      );
    return (
      matchesHeadingStyle ||
      (index > PDF_IMPORT_PROFILE.text.genericSectionHeadingSkipLines &&
        line.fontSize >
          bodyFontSize * PDF_IMPORT_PROFILE.text.genericSectionHeadingScale)
    );
  };
}

function sizeTolerance(fontSize: number) {
  return Math.max(0.25, fontSize * 0.025);
}

export function looksLikeUndatedItemHeading(
  candidate: TextLine,
  next: TextLine | undefined,
  first: TextLine,
) {
  return Boolean(
    next &&
    next.page === candidate.page &&
    next.y < candidate.y &&
    candidate.fontName &&
    next.fontName &&
    candidate.fontName === first.fontName &&
    candidate.fontName !== next.fontName &&
    Math.abs(candidate.fontSize - first.fontSize) <=
      sizeTolerance(first.fontSize) &&
    Math.abs(candidate.x - first.x) <= first.fontSize / 2,
  );
}
