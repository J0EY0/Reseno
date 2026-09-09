import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

import { waitForPdfImport } from "./abort";
import { PdfImportError } from "./errors";

import { PDF_IMPORT_PROFILE, median } from "./parser-config";
import {
  countTextGraphemes,
  isSingleHanGrapheme,
  normalizePdfCompatibilityCharacters,
  normalizeWhitespace,
} from "./text-heuristics";

type PdfTextItem = {
  str?: string;
  dir?: string;
  transform?: number[];
  width?: number;
  height?: number;
};

type PdfTextContent = {
  items?: PdfTextItem[];
};

type PdfPage = {
  getTextContent(): Promise<PdfTextContent>;
  getViewport(params: { scale: number }): { width: number };
};

type PdfDocument = {
  numPages: number;
  getPage(pageNumber: number): Promise<PdfPage>;
};

type PdfJsModule = {
  GlobalWorkerOptions: {
    workerSrc: string;
  };
  getDocument(source: { data: Uint8Array }): {
    promise: Promise<PdfDocument>;
    destroy(): Promise<void>;
  };
};

export type TextLine = {
  text: string;
  page: number;
  pageWidth?: number;
  x: number;
  y: number;
  fontSize: number;
};
type PositionedTextItem = {
  text: string;
  direction: "ltr" | "rtl";
  sourceIndex: number;
  x: number;
  y: number;
  fontSize: number;
  width: number;
};
export const MAX_PDF_IMPORT_BYTES = 10 * 1024 * 1024;
export const MAX_PDF_IMPORT_PAGES = 50;

export async function extractPdfLines(
  file: File,
  { signal }: { signal?: AbortSignal } = {},
): Promise<TextLine[]> {
  signal?.throwIfAborted();
  if (file.size > MAX_PDF_IMPORT_BYTES) {
    throw new PdfImportError("PDF_IMPORT_FILE_TOO_LARGE");
  }
  const [pdfjs, buffer] = await waitForPdfImport(
    Promise.all([loadPdfJs(), file.arrayBuffer()]),
    signal,
  );
  signal?.throwIfAborted();
  const loadingTask = pdfjs.getDocument({ data: new Uint8Array(buffer) });
  let destruction: Promise<void> | undefined;
  const destroy = () => (destruction ??= loadingTask.destroy());
  const onAbort = () => {
    void destroy().catch(() => {});
  };
  signal?.addEventListener("abort", onAbort, { once: true });

  try {
    const document = await waitForPdfImport(loadingTask.promise, signal);
    if (document.numPages > MAX_PDF_IMPORT_PAGES) {
      throw new PdfImportError("PDF_IMPORT_TOO_MANY_PAGES");
    }
    const lines: TextLine[] = [];
    for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
      signal?.throwIfAborted();
      const page = await waitForPdfImport(document.getPage(pageNumber), signal);
      const content = await waitForPdfImport(page.getTextContent(), signal);
      const pageWidth = page.getViewport({ scale: 1 }).width;
      lines.push(
        ...textContentToLinesForResumeImport(content, pageNumber, pageWidth),
      );
    }
    return lines;
  } finally {
    signal?.removeEventListener("abort", onAbort);
    await destroy();
  }
}

async function loadPdfJs(): Promise<PdfJsModule> {
  const pdfjs = (await import("pdfjs-dist/build/pdf.mjs")) as PdfJsModule;
  pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;
  return pdfjs;
}

export function textContentToLinesForResumeImport(
  content: PdfTextContent,
  page: number,
  pageWidth = 0,
): TextLine[] {
  // PDF.js exposes positioned text fragments, not logical lines. Rebuild lines
  // from the document's own font/width statistics so different templates do
  // not depend on a single fixed y-threshold or word-gap value.
  const items = dedupePositionedTextItems(
    (content.items ?? [])
      .filter((item) => typeof item.str === "string" && item.str.trim())
      .map<PositionedTextItem>((item, sourceIndex) => {
        const transform = item.transform ?? [];
        return {
          text: String(item.str ?? "").trim(),
          direction: item.dir === "rtl" ? "rtl" : "ltr",
          sourceIndex,
          x: Number(transform[4] ?? 0),
          y: Number(transform[5] ?? 0),
          fontSize: resolveTextItemFontSize(item, transform),
          width: Number(item.width ?? 0),
        };
      }),
  );

  const lineTolerance = estimateLineTolerance(items);
  const wordGap = estimateWordGap(items);
  const buckets = groupTextItemsByLine(items, lineTolerance);

  const lines = buckets
    .flatMap((bucket) => {
      // Fragments in opposite columns often have baselines that differ by
      // 1-2pt. Once PDF.js has grouped them into one visual row, retain that
      // shared y-coordinate so right-side metadata cannot sort before the
      // left-side title later in the import pipeline.
      const visualRowY = median(bucket.map((item) => item.y));
      return splitLineBucketByColumnGap(bucket, wordGap).map((column) =>
        textItemBucketToLine(column, page, pageWidth, wordGap, visualRowY),
      );
    })
    .filter((line) => line.text);

  return orderLinesForReading(lines);
}

function dedupePositionedTextItems(items: PositionedTextItem[]) {
  const acceptedByText = new Map<string, PositionedTextItem[]>();
  return items.filter((item) => {
    // Hidden accessibility/text layers are often offset by a fraction of a
    // point from their visible counterpart. Compare only equal normalized text
    // within a font-relative coordinate tolerance; repeated authored text at a
    // different position must remain intact.
    const key = normalizeWhitespace(item.text);
    const accepted = acceptedByText.get(key) ?? [];
    const isDuplicate = accepted.some((candidate) => {
      const tolerance = Math.max(
        PDF_IMPORT_PROFILE.layout.minDuplicatePositionTolerance,
        Math.max(item.fontSize, candidate.fontSize) *
          PDF_IMPORT_PROFILE.layout.duplicatePositionToleranceScale,
      );
      return (
        Math.abs(item.x - candidate.x) <= tolerance &&
        Math.abs(item.y - candidate.y) <= tolerance
      );
    });
    if (isDuplicate) {
      return false;
    }

    accepted.push(item);
    acceptedByText.set(key, accepted);
    return true;
  });
}

function resolveTextItemFontSize(item: PdfTextItem, transform: number[]) {
  const reportedHeight = Math.abs(Number(item.height ?? 0));
  if (Number.isFinite(reportedHeight) && reportedHeight > 0) {
    return reportedHeight;
  }

  // Rotated text can have a zero vertical scale component. The two basis-vector
  // lengths recover the rendered size without assuming a particular rotation.
  const horizontalScale = Math.hypot(
    Number(transform[0] ?? 0),
    Number(transform[1] ?? 0),
  );
  const verticalScale = Math.hypot(
    Number(transform[2] ?? 0),
    Number(transform[3] ?? 0),
  );
  return Math.max(horizontalScale, verticalScale);
}

function groupTextItemsByLine(
  items: PositionedTextItem[],
  lineTolerance: number,
) {
  const buckets: PositionedTextItem[][] = [];

  for (const item of items) {
    const bucket = buckets.find(
      (candidate) =>
        Math.abs((candidate[0]?.y ?? item.y) - item.y) <= lineTolerance,
    );

    if (bucket) {
      bucket.push(item);
    } else {
      buckets.push([item]);
    }
  }

  return buckets;
}

function splitLineBucketByColumnGap(
  bucket: PositionedTextItem[],
  wordGap: number,
) {
  const sorted = [...bucket].sort((left, right) => left.x - right.x);
  const columnGap = wordGap * PDF_IMPORT_PROFILE.layout.minColumnGapWords;
  const lines: PositionedTextItem[][] = [];
  let current: PositionedTextItem[] = [];
  let previousEnd = 0;

  for (const item of sorted) {
    const gap = item.x - previousEnd;
    if (current.length > 0 && gap > columnGap) {
      lines.push(current);
      current = [];
    }

    current.push(item);
    previousEnd = item.x + item.width;
  }

  if (current.length > 0) {
    lines.push(current);
  }

  return lines;
}

function textItemBucketToLine(
  bucket: PositionedTextItem[],
  page: number,
  pageWidth: number,
  wordGap: number,
  visualRowY: number,
): TextLine {
  const direction = dominantTextDirection(bucket);
  const sorted = [...bucket].sort((left, right) =>
    direction === "rtl" ? right.x - left.x : left.x - right.x,
  );
  const text = joinLineItems(sorted, wordGap, direction);
  const averageFontSize =
    sorted.reduce((sum, item) => sum + item.fontSize, 0) / sorted.length;

  return {
    text,
    page,
    pageWidth: pageWidth > 0 ? pageWidth : undefined,
    x: Math.min(...sorted.map((item) => item.x)),
    y: visualRowY,
    fontSize: averageFontSize,
  };
}

function dominantTextDirection(items: PositionedTextItem[]) {
  const directionWeights = items.reduce(
    (weights, item) => {
      weights[item.direction] += countTextGraphemes(item.text);
      return weights;
    },
    { ltr: 0, rtl: 0 },
  );
  if (directionWeights.rtl !== directionWeights.ltr) {
    return directionWeights.rtl > directionWeights.ltr ? "rtl" : "ltr";
  }

  // Equal visible-text weights are uncommon, but choosing the first authored
  // token keeps mixed-direction lines stable instead of always forcing LTR.
  return (
    [...items]
      .sort((left, right) => left.sourceIndex - right.sourceIndex)
      .find((item) => countTextGraphemes(item.text) > 0)?.direction ?? "ltr"
  );
}

function estimateLineTolerance(items: PositionedTextItem[]) {
  const fontSize = median(items.map((item) => item.fontSize).filter(Boolean));
  return Math.max(
    PDF_IMPORT_PROFILE.layout.minLineTolerance,
    fontSize * PDF_IMPORT_PROFILE.layout.lineToleranceScale,
  );
}

function estimateWordGap(items: PositionedTextItem[]) {
  const widths = items
    .map((item) => item.width / Math.max(countTextGraphemes(item.text), 1))
    .filter((width) => Number.isFinite(width) && width > 0);
  return Math.max(
    PDF_IMPORT_PROFILE.layout.minWordGap,
    median(widths) * PDF_IMPORT_PROFILE.layout.wordGapScale,
  );
}

function joinLineItems(
  items: Array<{ text: string; x: number; width: number }>,
  wordGap: number,
  direction: "ltr" | "rtl",
) {
  let line = "";
  let previousItem: { text: string; x: number; width: number } | null = null;
  for (const item of items) {
    const gap = previousItem
      ? direction === "rtl"
        ? previousItem.x - (item.x + item.width)
        : item.x - (previousItem.x + previousItem.width)
      : 0;
    // PDF.js preserves the physical width of an authored space but often
    // splits the text immediately around it. That width is much smaller than
    // the conservative threshold used to detect separate columns, so use a
    // dedicated threshold when reconstructing readable line text.
    const separator =
      line &&
      previousItem &&
      shouldSeparateTextItems(previousItem, item, gap, wordGap)
        ? " "
        : "";
    line = `${line}${separator}${item.text}`;
    previousItem = item;
  }

  return normalizeWhitespace(line);
}

function shouldSeparateTextItems(
  previous: { text: string },
  current: { text: string },
  gap: number,
  wordGap: number,
) {
  if (
    gap <=
    Math.max(
      PDF_IMPORT_PROFILE.layout.minLineTolerance,
      wordGap * PDF_IMPORT_PROFILE.layout.spaceGapScale,
    )
  ) {
    return false;
  }

  const previousText = normalizePdfCompatibilityCharacters(previous.text);
  const currentText = normalizePdfCompatibilityCharacters(current.text);
  // PDF.js can emit punctuation as a separate token whose bounding box starts
  // after a small visual gap. Unicode punctuation still belongs to the
  // adjacent text, so do not turn that glyph positioning into an authored
  // space (for example, `语言 ：` instead of `语言：`).
  if (
    /^(?:[\p{Pe}\p{Pf}\p{M}]|[,.;:!?，。；：！？、%％])/u.test(currentText) ||
    /[\p{Ps}\p{Pi}]$/u.test(previousText)
  ) {
    return false;
  }
  // Some embedded fonts expose every Han glyph as a separate PDF.js token
  // whose advance is slightly wider than its reported box. A visual gap there
  // is glyph positioning, not an authored word separator.
  if (isSingleHanGrapheme(previousText) && isSingleHanGrapheme(currentText)) {
    return false;
  }

  return true;
}

export function orderLinesForReading(lines: TextLine[]) {
  const pages = new Map<number, TextLine[]>();
  for (const line of lines) {
    const pageLines = pages.get(line.page) ?? [];
    pageLines.push(line);
    pages.set(line.page, pageLines);
  }

  return [...pages.entries()]
    .sort(([leftPage], [rightPage]) => leftPage - rightPage)
    .flatMap(([, pageLines]) => orderPageLinesForReading(pageLines));
}

function orderPageLinesForReading(lines: TextLine[]) {
  const visualOrder = sortLinesTopToBottom(lines);
  if (
    lines.length <
    PDF_IMPORT_PROFILE.layout.minLeftColumnLines +
      PDF_IMPORT_PROFILE.layout.minRightColumnLines
  ) {
    return visualOrder;
  }

  const bodyFontSize = median(
    lines.map((line) => line.fontSize).filter(Boolean),
  );
  const clusterTolerance =
    bodyFontSize * PDF_IMPORT_PROFILE.layout.columnStartClusterScale;
  const clusters = clusterLineStarts(lines, clusterTolerance);
  const minimumX = Math.min(...lines.map((line) => line.x));
  const maximumX = Math.max(...lines.map((line) => line.x));
  const measuredPageWidths = lines
    .map((line) => line.pageWidth ?? 0)
    .filter((width) => width > 0);
  const pageWidth =
    measuredPageWidths.length > 0
      ? median(measuredPageWidths)
      : maximumX - minimumX;

  // A real body column repeats the same x start over many rows. Right-aligned
  // dates and scores occur at several unrelated x positions, so they do not
  // form a large cluster and remain in normal visual-row order.
  const rightColumn = clusters.find(
    (cluster) =>
      cluster.lines.length >= PDF_IMPORT_PROFILE.layout.minRightColumnLines &&
      cluster.center - minimumX >=
        bodyFontSize * PDF_IMPORT_PROFILE.layout.columnStartGapScale &&
      cluster.center - minimumX >=
        pageWidth * PDF_IMPORT_PROFILE.layout.minRightColumnStartRatio &&
      cluster.center - minimumX <=
        pageWidth * PDF_IMPORT_PROFILE.layout.maxRightColumnStartRatio,
  );
  if (!rightColumn) {
    return visualOrder;
  }

  const provenBands = splitColumnLinesIntoBands(rightColumn.lines, bodyFontSize)
    .filter(
      (rightLines) =>
        rightLines.length >= PDF_IMPORT_PROFILE.layout.minRightColumnLines,
    )
    .map((rightLines) =>
      createProvenColumnBand(
        lines,
        rightLines,
        rightColumn.center - clusterTolerance,
        bodyFontSize,
      ),
    )
    .filter((band): band is ProvenColumnBand => band !== null)
    .sort((left, right) => right.top - left.top);
  if (provenBands.length === 0) {
    return visualOrder;
  }

  // A page may contain multiple independent two-column regions separated by
  // full-width content. Reorder each proven band independently so content
  // between those regions keeps its visual position.
  let remaining = visualOrder;
  const ordered: TextLine[] = [];
  for (const band of provenBands) {
    ordered.push(...remaining.filter((line) => line.y > band.top));
    ordered.push(...sortLinesTopToBottom(band.leftLines));
    ordered.push(...sortLinesTopToBottom(band.rightLines));
    remaining = remaining.filter((line) => line.y < band.bottom);
  }
  return [...ordered, ...remaining];
}

type ProvenColumnBand = {
  top: number;
  bottom: number;
  leftLines: TextLine[];
  rightLines: TextLine[];
};

function splitColumnLinesIntoBands(lines: TextLine[], bodyFontSize: number) {
  const sorted = sortLinesTopToBottom(lines);
  const maximumGap =
    bodyFontSize * PDF_IMPORT_PROFILE.layout.maxColumnBandGapScale;
  const bands: TextLine[][] = [];
  let current: TextLine[] = [];

  for (const line of sorted) {
    const previous = current.at(-1);
    if (previous && previous.y - line.y > maximumGap) {
      bands.push(current);
      current = [];
    }
    current.push(line);
  }
  if (current.length > 0) {
    bands.push(current);
  }

  return bands;
}

function createProvenColumnBand(
  lines: TextLine[],
  rightLines: TextLine[],
  boundary: number,
  bodyFontSize: number,
): ProvenColumnBand | null {
  const padding =
    bodyFontSize * PDF_IMPORT_PROFILE.layout.headerRowToleranceScale;
  const top = Math.max(...rightLines.map((line) => line.y)) + padding;
  const bottom = Math.min(...rightLines.map((line) => line.y)) - padding;
  const bandLines = lines.filter((line) => line.y <= top && line.y >= bottom);
  const leftLines = bandLines.filter((line) => line.x < boundary);
  const resolvedRightLines = bandLines.filter((line) => line.x >= boundary);

  if (
    leftLines.length < PDF_IMPORT_PROFILE.layout.minLeftColumnLines ||
    resolvedRightLines.length < PDF_IMPORT_PROFILE.layout.minRightColumnLines ||
    !columnsShareVerticalRange(leftLines, resolvedRightLines, bodyFontSize)
  ) {
    return null;
  }

  return { top, bottom, leftLines, rightLines: resolvedRightLines };
}

function clusterLineStarts(lines: TextLine[], tolerance: number) {
  const sorted = [...lines].sort((left, right) => left.x - right.x);
  const clusters: Array<{ center: number; lines: TextLine[] }> = [];

  for (const line of sorted) {
    const current = clusters.at(-1);
    if (current && Math.abs(line.x - current.center) <= tolerance) {
      current.lines.push(line);
      current.center = median(current.lines.map((candidate) => candidate.x));
    } else {
      clusters.push({ center: line.x, lines: [line] });
    }
  }

  return clusters;
}

function columnsShareVerticalRange(
  leftLines: TextLine[],
  rightLines: TextLine[],
  bodyFontSize: number,
) {
  const leftTop = Math.max(...leftLines.map((line) => line.y));
  const leftBottom = Math.min(...leftLines.map((line) => line.y));
  const rightTop = Math.max(...rightLines.map((line) => line.y));
  const rightBottom = Math.min(...rightLines.map((line) => line.y));
  const overlap =
    Math.min(leftTop, rightTop) - Math.max(leftBottom, rightBottom);
  return (
    overlap >=
    bodyFontSize * PDF_IMPORT_PROFILE.layout.minColumnVerticalOverlapScale
  );
}

function sortLinesTopToBottom(lines: TextLine[]) {
  return [...lines].sort((left, right) => right.y - left.y || left.x - right.x);
}
