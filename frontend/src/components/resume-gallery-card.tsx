import { Check, Clock3, Trash2 } from "lucide-react";
import { memo } from "react";
import { Link } from "react-router-dom";

import { ResumeThumbnail } from "@/components/preview/resume-thumbnail";
import { Button } from "@/components/ui/button";
import type { AppMessages } from "@/i18n";
import { useLocalizedMessages } from "@/i18n/use-localized-messages";
import { cn } from "@/lib/utils";
import type {
  ResumeTemplateDefinition,
  ResumeWorkspaceItem,
} from "@/types/resume";

export const ResumeGalleryCard = memo(function ResumeGalleryCard({
  t,
  item,
  template,
  isSelecting,
  isSelected,
  isOpening,
  showDeleteAction,
  updatedAtFormatter,
  onPreloadDetail,
  onOpenResume,
  onRequestDelete,
  onToggleSelected,
}: {
  t: AppMessages;
  item: ResumeWorkspaceItem;
  template: ResumeTemplateDefinition;
  isSelecting: boolean;
  isSelected: boolean;
  isOpening: boolean;
  showDeleteAction: boolean;
  updatedAtFormatter: Intl.DateTimeFormat;
  onPreloadDetail: () => void;
  onOpenResume: (resumeId: string) => void;
  onRequestDelete: (resumeIds: string[]) => void;
  onToggleSelected: (resumeId: string) => void;
}) {
  const resumeLabel = item.title || item.resume.basic.name || t.untitledResume;
  const preloadDetail = isSelecting ? undefined : onPreloadDetail;
  const documentMessages = useLocalizedMessages(item.documentLocale);

  return (
    <div
      data-gallery-item-id={item.id}
      className="group relative h-full"
    >
        <Link
          to={`/resume/${item.id}`}
          role={isSelecting ? "button" : undefined}
          aria-label={resumeLabel}
          aria-pressed={isSelecting ? isSelected : undefined}
          aria-busy={isOpening || undefined}
          className="block h-full rounded-(--radius-card) text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          onPointerEnter={preloadDetail}
          onFocus={preloadDetail}
          onPointerDown={preloadDetail}
          onClick={(event) => {
            if (isSelecting) {
              event.preventDefault();
              onToggleSelected(item.id);
              return;
            }
            if (
              event.button === 0 &&
              !event.metaKey &&
              !event.ctrlKey &&
              !event.shiftKey &&
              !event.altKey
            ) {
              event.preventDefault();
              onOpenResume(item.id);
            }
          }}
          onKeyDown={(event) => {
            if (isSelecting && event.key === " ") {
              event.preventDefault();
              onToggleSelected(item.id);
            }
          }}
        >
          <div
            className={cn(
              "flex h-full flex-col rounded-(--radius-card) border border-border/80 bg-card p-2.5 shadow-card transition-colors duration-200 group-hover:border-border group-hover:bg-accent/20",
              isSelected && "border-primary bg-accent/20",
            )}
          >
            <div className="rounded-xl bg-muted/55 p-2">
              <div className="relative mx-auto h-[258px] w-[182px] overflow-hidden rounded-lg border border-zinc-200 bg-white">
                {isSelecting ? (
                  <span
                    aria-hidden="true"
                    className={cn(
                      "absolute left-3 top-3 z-10 flex size-7 items-center justify-center rounded-full border backdrop-blur",
                      isSelected
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border/80 bg-background/92 text-muted-foreground",
                    )}
                  >
                    <Check className="size-3.5" />
                  </span>
                ) : null}
                {documentMessages ? (
                  <div
                    aria-hidden="true"
                    className="pointer-events-none absolute left-0 top-0 origin-top-left scale-[0.224]"
                    style={{ width: "210mm", height: "297mm" }}
                  >
                    <ResumeThumbnail
                      t={documentMessages}
                      resume={item.resume}
                      fontFamily={item.typography.fontFamily}
                      fontSize={item.typography.fontSize}
                      template={template}
                    />
                  </div>
                ) : null}
              </div>
            </div>
            <div className="flex min-h-[92px] flex-1 flex-col justify-between px-1 pt-3">
              <div>
                <p className="truncate text-[15px] font-semibold" title={resumeLabel}>
                  {resumeLabel}
                </p>
                <p className="mt-1 truncate text-xs text-muted-foreground">
                  {item.resume.basic.headline ||
                    item.resume.basic.email ||
                    item.resume.basic.phone}
                </p>
              </div>
              <p className="mt-2 inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <Clock3 className="size-3" />
                {updatedAtFormatter.format(new Date(item.updatedAt))}
              </p>
            </div>
          </div>
        </Link>
        {showDeleteAction ? (
          <Button
            type="button"
            variant="destructive"
            size="icon-sm"
            aria-label={t.confirmDeleteAction}
            className="absolute right-8 top-8 z-10 size-7 rounded-full backdrop-blur"
            onClick={() => onRequestDelete([item.id])}
          >
            <Trash2 className="size-3.5" />
          </Button>
        ) : null}
    </div>
  );
});
