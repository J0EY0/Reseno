import { diffArrays } from "diff/lib/diff/array.js";
import { diffWords } from "diff/lib/diff/word.js";

interface InlineDiffPart {
  changed: boolean;
  value: string;
}

export interface ListDiff {
  changedIndices: Set<number>;
  hasDeletions: boolean;
}

const wordSegmenter = new Intl.Segmenter("zh-CN", { granularity: "word" });

export function createInlineDiffParts(
  before: string,
  after: string,
): InlineDiffPart[] {
  return diffWords(before, after, { intlSegmenter: wordSegmenter })
    .filter((part) => !part.removed)
    .map((part) => ({
      changed: Boolean(part.added),
      value: part.value,
    }));
}

export function createListDiff(before: string[], after: string[]): ListDiff {
  const changedIndices = new Set<number>();
  let hasDeletions = false;
  let afterIndex = 0;
  const parts = diffArrays(before, after);

  for (const [partIndex, part] of parts.entries()) {
    if (part.removed) {
      if (!parts[partIndex + 1]?.added) {
        hasDeletions = true;
      }
      continue;
    }
    if (part.added) {
      for (let index = 0; index < part.value.length; index += 1) {
        changedIndices.add(afterIndex + index);
      }
    }
    afterIndex += part.value.length;
  }

  return { changedIndices, hasDeletions };
}
