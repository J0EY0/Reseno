import { Fragment } from "react";

import { ResumeDiffText } from "@/components/preview/resume-preview-diff-text";
import {
  getCanonicalItemFieldDiffs,
  type ItemDiffLookup,
} from "@/components/preview/resume-preview-diffs";
import type { RenderableSectionItem } from "@/lib/resume-sections";
import { cn } from "@/lib/utils";
import type { ResumeDraftDiff } from "@/types/resume";

type RenderableItemTextPart = NonNullable<
  RenderableSectionItem["subtitleParts"]
>[number];

export function ResumeItemText({
  diff,
  fallbackDiffs,
  parts,
  richText = true,
  value,
}: {
  diff?: ItemDiffLookup;
  fallbackDiffs: ResumeDraftDiff[];
  parts?: RenderableItemTextPart[];
  richText?: boolean;
  value: string;
}) {
  if (!parts) {
    return <ResumeDiffText richText={richText} value={value} diffs={fallbackDiffs} />;
  }

  return parts.map((part, index) => {
    const partDiffs = getCanonicalItemFieldDiffs(diff, part.field);
    if (!part.value && partDiffs.length === 0) {
      return null;
    }
    const hasPreviousText = parts
      .slice(0, index)
      .some((candidate) => Boolean(candidate.value));

    return (
      <Fragment key={part.field}>
        {part.value && hasPreviousText ? " · " : null}
        <span
          className={cn(!part.value && "resume-diff-empty-slot")}
          data-resume-field={part.field}
        >
          <ResumeDiffText richText={richText} value={part.value} diffs={partDiffs} />
        </span>
      </Fragment>
    );
  });
}
