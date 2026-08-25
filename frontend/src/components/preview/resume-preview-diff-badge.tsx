import { Badge } from "@/components/ui/badge";
import { getDiffLabel } from "@/components/preview/resume-preview-model";
import type { AppMessages } from "@/i18n";
import type { ResumeDraftDiff } from "@/types/resume";

export function ResumeDiffBadge({
  diff,
  t,
}: {
  diff?: ResumeDraftDiff;
  t: AppMessages;
}) {
  const label = getDiffLabel(diff, t);

  if (!diff || !label) {
    return null;
  }

  return (
    <Badge
      className="resume-diff-badge"
      data-resume-diff-badge="true"
      data-resume-diff-kind={diff.kind}
      variant="outline"
    >
      {label}
    </Badge>
  );
}
