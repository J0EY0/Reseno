import type {
  ItemDiffLookup,
  ResumeDiffLookup,
  SectionDiffLookup,
} from "@/components/preview/resume-preview-diffs";
import { compactResumeDraftDiffs } from "@/lib/agent-diff-value";
import type { ResumeDraftDiff } from "@/types/resume";

function itemFieldName(diff: ResumeDraftDiff) {
  if (!diff.sectionId || !diff.itemId) {
    return null;
  }
  const prefix = `sections.${diff.sectionId}.items.${diff.itemId}.`;
  return diff.path.startsWith(prefix) ? diff.path.slice(prefix.length) : null;
}

export function createResumeDiffLookup(
  diffs: ResumeDraftDiff[],
): ResumeDiffLookup {
  const basicDiffByField = new Map<string, ResumeDraftDiff>();
  const deletedItemDiffsBySectionId = new Map<string, ResumeDraftDiff[]>();
  const deletedSectionDiffs: ResumeDraftDiff[] = [];
  const itemDiffById = new Map<string, ItemDiffLookup>();
  const sectionDiffById = new Map<string, SectionDiffLookup>();

  for (const diff of compactResumeDraftDiffs(diffs)) {
    if (diff.path.startsWith("basic.")) {
      const field = diff.path.slice("basic.".length);
      basicDiffByField.set(field, diff);
      continue;
    }

    if (diff.itemId) {
      if (diff.kind === "deleted") {
        const deletedItems =
          deletedItemDiffsBySectionId.get(diff.sectionId ?? "") ?? [];
        deletedItems.push(diff);
        deletedItemDiffsBySectionId.set(diff.sectionId ?? "", deletedItems);
        continue;
      }
      const itemLookup = itemDiffById.get(diff.itemId) ?? {
        fieldDiffByName: new Map<string, ResumeDraftDiff>(),
      };
      const field = itemFieldName(diff);
      if (diff.kind === "modified" && field) {
        itemLookup.fieldDiffByName.set(field, diff);
      } else {
        itemLookup.structuralDiff = diff;
      }
      itemDiffById.set(diff.itemId, itemLookup);
      continue;
    }

    if (diff.sectionId) {
      if (diff.kind === "deleted") {
        deletedSectionDiffs.push(diff);
        continue;
      }
      const sectionLookup = sectionDiffById.get(diff.sectionId) ?? {};
      if (
        diff.kind === "modified" &&
        diff.path === `sections.${diff.sectionId}.title`
      ) {
        sectionLookup.titleDiff = diff;
      } else {
        sectionLookup.structuralDiff = diff;
      }
      sectionDiffById.set(diff.sectionId, sectionLookup);
    }
  }

  return {
    basicDiffByField,
    deletedItemDiffsBySectionId,
    deletedSectionDiffs,
    itemDiffById,
    sectionDiffById,
  };
}
