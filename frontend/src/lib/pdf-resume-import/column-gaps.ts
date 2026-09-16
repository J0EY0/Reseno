import { median, PDF_IMPORT_PROFILE } from "./parser-config";

type PositionedFragment = {
  x: number;
  y: number;
  width: number;
  fontSize: number;
  sourceIndex: number;
};

type ColumnGap = {
  row: number;
  right: PositionedFragment;
  leftStart: number;
};

export function findRepeatedColumnStarts(
  buckets: PositionedFragment[][],
  wordGap: number,
  pageWidth: number,
) {
  const starts = new Set<number>();
  const rows = buckets
    .map((bucket) => [...bucket].sort((left, right) => left.x - right.x))
    .sort((left, right) => (right[0]?.y ?? 0) - (left[0]?.y ?? 0));
  const minimumX = Math.min(
    ...rows.flatMap((row) => row.map((item) => item.x)),
  );
  const gaps: ColumnGap[] = [];

  for (const [rowIndex, row] of rows.entries()) {
    for (let index = 1; index < row.length; index += 1) {
      const right = row[index];
      const left = row[index - 1];
      const offset = right.x - minimumX;
      if (
        right.x - (left.x + left.width) > wordGap &&
        offset >=
          right.fontSize * PDF_IMPORT_PROFILE.layout.columnStartGapScale &&
        (pageWidth <= 0 ||
          (offset >=
            pageWidth * PDF_IMPORT_PROFILE.layout.minRightColumnStartRatio &&
            offset <=
              pageWidth * PDF_IMPORT_PROFILE.layout.maxRightColumnStartRatio))
      ) {
        gaps.push({ row: rowIndex, right, leftStart: row[0].x });
      }
    }
  }

  for (const gap of gaps) {
    const aligned = gaps.filter(
      (candidate) =>
        Math.abs(candidate.right.x - gap.right.x) <= wordGap / 2 &&
        Math.abs(candidate.leftStart - gap.leftStart) <= wordGap / 2,
    );
    const fontSize = median(
      aligned.map((candidate) => candidate.right.fontSize),
    );
    let band: ColumnGap[] = [];
    const retainBand = () => {
      if (band.length >= 3) {
        for (const candidate of band) starts.add(candidate.right.sourceIndex);
      }
    };
    for (const candidate of aligned) {
      const previous = band.at(-1);
      if (
        previous &&
        (candidate.row !== previous.row + 1 ||
          previous.right.y - candidate.right.y >
            fontSize * PDF_IMPORT_PROFILE.layout.listContinuationGapScale)
      ) {
        retainBand();
        band = [];
      }
      band.push(candidate);
    }
    retainBand();
  }

  return starts;
}
