import { Check, Sparkles, Trash2 } from "lucide-react";
import { memo } from "react";
import { Link } from "react-router-dom";

import { ResumeThumbnail } from "@/components/preview/resume-thumbnail";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type { AppMessages } from "@/i18n";
import { cn } from "@/lib/utils";
import type {
  ResumeData,
  ResumeTemplateDefinition,
} from "@/types/resume";

export const TemplateGalleryCard = memo(function TemplateGalleryCard({
  t,
  previewResume,
  template,
  isDefaultTemplate,
  isSelecting,
  isSelected,
  isOpening,
  settingDefaultTemplateId,
  onPreloadDetail,
  onOpenTemplate,
  onRequestDelete,
  onSetDefaultTemplate,
  onToggleSelected,
}: {
  t: AppMessages;
  previewResume: ResumeData;
  template: ResumeTemplateDefinition;
  isDefaultTemplate: boolean;
  isSelecting: boolean;
  isSelected: boolean;
  isOpening: boolean;
  settingDefaultTemplateId: string | null;
  onPreloadDetail: () => void;
  onOpenTemplate: (templateId: string) => void;
  onRequestDelete: (templateIds: string[]) => void;
  onSetDefaultTemplate: (templateId: string) => void;
  onToggleSelected: (templateId: string) => void;
}) {
  const preloadDetail = isSelecting ? undefined : onPreloadDetail;
  const canSelect = isSelecting && !template.isBuiltIn;
  const isSelectableSelected = canSelect && isSelected;

  return (
    <div className="group relative h-full select-none">
        <div
          className={cn(
            "flex h-full flex-col rounded-(--radius-card) border border-border/80 bg-card p-2.5 shadow-card transition-colors duration-200",
            (!isSelecting || canSelect) &&
              "group-hover:border-border group-hover:bg-accent/20",
            isSelectableSelected && "border-primary bg-accent/20",
          )}
        >
          <Link
            to={`/template/${template.id}`}
            role={canSelect ? "button" : undefined}
            aria-label={template.name}
            className={cn(
              "block select-none rounded-xl text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              isSelecting && !canSelect ? "cursor-default" : "cursor-pointer",
            )}
            aria-pressed={canSelect ? isSelected : undefined}
            aria-disabled={isSelecting && template.isBuiltIn}
            aria-busy={isOpening || undefined}
            tabIndex={isSelecting && template.isBuiltIn ? -1 : undefined}
            onPointerEnter={preloadDetail}
            onFocus={preloadDetail}
            onPointerDown={preloadDetail}
            onClick={(event) => {
              if (isSelecting) {
                event.preventDefault();
                if (canSelect) {
                  onToggleSelected(template.id);
                }
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
                onOpenTemplate(template.id);
              }
            }}
            onKeyDown={(event) => {
              if (canSelect && event.key === " ") {
                event.preventDefault();
                onToggleSelected(template.id);
              }
            }}
          >
            <div className="rounded-xl bg-muted/55 p-2">
              <div className="relative mx-auto h-[258px] w-[182px] overflow-hidden rounded-lg border border-zinc-200 bg-white">
                <div
                  aria-hidden="true"
                  className="pointer-events-none absolute left-0 top-0 origin-top-left scale-[0.224]"
                  style={{ width: "210mm", height: "297mm" }}
                >
                  <ResumeThumbnail
                    t={t}
                    resume={previewResume}
                    fontFamily={template.typography.fontFamily}
                    fontSize={template.typography.fontSize}
                    template={template}
                    showEmptyTemplateImagePlaceholders
                  />
                </div>
                {canSelect ? (
                  <span
                    aria-hidden="true"
                    className={cn(
                      "absolute left-3 top-3 flex size-7 items-center justify-center rounded-full border bg-background/92 backdrop-blur transition-colors",
                      isSelectableSelected
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border/80 text-muted-foreground",
                    )}
                  >
                    <Check className="size-3.5" />
                  </span>
                ) : null}
              </div>
            </div>
          </Link>
          <div className="flex min-h-[92px] flex-1 flex-col justify-between px-1 pt-3">
            <div className="min-w-0">
              <p className="truncate text-[15px] font-semibold" title={template.name}>
                {template.name}
              </p>
              <p
                className="mt-1 line-clamp-2 min-h-8 text-xs text-muted-foreground"
                title={template.description || t.templateDescriptionFallback}
              >
                {template.description || t.templateDescriptionFallback}
              </p>
            </div>
            <div className="mt-2 flex items-center justify-between gap-2">
              {template.isBuiltIn ? (
                <Badge className="h-7 bg-transparent px-2.5 text-[11px] font-medium text-muted-foreground shadow-none">
                  <Sparkles className="mr-1 size-3.5" />
                  {t.builtInTemplate}
                </Badge>
              ) : (
                <span />
              )}
              {isSelecting ? null : isDefaultTemplate ? (
                <Badge
                  variant="outline"
                  className="h-7 rounded-full border-border/80 bg-muted px-2.5 text-[11px] font-medium text-muted-foreground"
                >
                  {t.defaultTemplateLabel}
                </Badge>
              ) : (
                <Button
                  type="button"
                  size="sm"
                  className="h-7 rounded-full px-2.5 text-[11px]"
                  disabled={settingDefaultTemplateId !== null}
                  onClick={() => onSetDefaultTemplate(template.id)}
                >
                  {settingDefaultTemplateId === template.id ? (
                    <Spinner data-icon="inline-start" aria-label={t.setDefaultTemplate} />
                  ) : null}
                  {t.setDefaultTemplate}
                </Button>
              )}
            </div>
          </div>
        </div>
        {isSelectableSelected ? (
          <Button
            type="button"
            variant="destructive"
            size="icon-sm"
            className="absolute right-8 top-8 z-10 size-7 rounded-full backdrop-blur"
            onClick={() => onRequestDelete([template.id])}
            aria-label={t.confirmDeleteAction}
          >
            <Trash2 className="size-3.5" />
          </Button>
        ) : null}
    </div>
  );
});
