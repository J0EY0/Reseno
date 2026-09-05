import { lazy, Suspense } from "react";

import { cn } from "@/lib/utils";
import type { ResumeDraftDiff } from "@/types/resume";

const PreciseResumeDiffText = lazy(() =>
  import("@/components/preview/resume-preview-diff-precision").then(
    ({ PreciseResumeDiffText: component }) => ({ default: component }),
  ),
);

function DiffTextFallback({
  className,
  diffs,
  value,
}: {
  className?: string;
  diffs: ResumeDraftDiff[];
  value: string;
}) {
  return (
    <span
      className={cn(
        "resume-diff-field resume-diff-field--whole",
        className,
      )}
      data-resume-diff-path={diffs.map((diff) => diff.path).join(" ")}
    >
      {value}
    </span>
  );
}

export function ResumeDiffText({
  className,
  diffs,
  value,
}: {
  className?: string;
  diffs: ResumeDraftDiff[];
  value: string;
}) {
  if (diffs.length === 0) {
    return <span className={className}>{value}</span>;
  }

  return (
    <Suspense
      fallback={
        <DiffTextFallback className={className} diffs={diffs} value={value} />
      }
    >
      <PreciseResumeDiffText
        className={className}
        diffs={diffs}
        value={value}
      />
    </Suspense>
  );
}
