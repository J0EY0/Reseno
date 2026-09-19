import { Skeleton } from "@/components/ui/skeleton";
import { serializeHighlightsToHtml } from "@/lib/rich-text";

import {
  getRichHighlightsEditorContent,
  richHighlightsEditorContainerClassName,
  richHighlightsEditorContentClassName,
} from "./rich-highlights-editor-content";

export function RichHighlightsEditorSkeleton({
  label,
  value,
}: {
  label: string;
  value: string[];
}) {
  const previewValue = getRichHighlightsEditorContent(
    serializeHighlightsToHtml(value),
  ).replaceAll("<p></p>", "<p><br></p>");

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <span className="text-xs font-medium leading-tight text-muted-foreground">
        {label}
      </span>
      <div className={richHighlightsEditorContainerClassName}>
        <div className="flex flex-wrap items-center gap-0.5 p-2 pb-0">
          {Array.from({ length: 5 }, (_, index) => (
            <Skeleton key={index} className="size-8 rounded-md" />
          ))}
        </div>
        <Skeleton className="rounded-none">
          <div
            aria-hidden="true"
            className={`${richHighlightsEditorContentClassName} invisible`}
            dangerouslySetInnerHTML={{ __html: previewValue }}
          />
        </Skeleton>
      </div>
    </div>
  );
}
