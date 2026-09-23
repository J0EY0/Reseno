import { ResumeDiffText } from "@/components/preview/resume-preview-diff-text";
import {
  getRenderableFieldDiffs,
  type ItemDiffLookup,
  type RenderableItemField,
} from "@/components/preview/resume-preview-diffs";
import { ResumeItemText } from "@/components/preview/resume-preview-item-text";
import type { RenderableSectionItem } from "@/lib/resume-sections";
import { cn } from "@/lib/utils";
import type {
  ResumeDraftDiff,
  ResumeTemplateSettings,
  ResumeTimelineItemLayout,
  SectionKind,
} from "@/types/resume";

function hasTextSlot(
  value: string,
  fallbackDiffs: ResumeDraftDiff[],
  parts: RenderableSectionItem["subtitleParts"],
) {
  return Boolean(
    value || fallbackDiffs.length > 0 || parts?.some((part) => part.value),
  );
}

export function TimelineItemHeading({
  diff,
  item,
  kind,
  layout,
  settings,
}: {
  diff?: ItemDiffLookup;
  item: RenderableSectionItem;
  kind: SectionKind;
  layout: ResumeTimelineItemLayout;
  settings: ResumeTemplateSettings;
}) {
  const fieldDiffs = (field: RenderableItemField) =>
    getRenderableFieldDiffs(diff, kind, field);
  const subtitleDiffs = fieldDiffs("subtitle");
  const metaDiffs = fieldDiffs("meta");
  const periodDiffs = fieldDiffs("period");
  const hasSubtitle = hasTextSlot(
    item.subtitle,
    subtitleDiffs,
    item.subtitleParts,
  );
  const hasMeta = hasTextSlot(item.meta, metaDiffs, item.metaParts);
  const hasPeriod = Boolean(item.period || periodDiffs.length > 0);
  const title = (
    <h3
      className={cn(
        "min-w-0 font-extrabold",
        layout === "inline" ? "wrap-anywhere" : "break-words",
      )}
      style={{
        color: settings.bodyColor,
        fontSize: `${settings.itemTitleScale}em`,
      }}
    >
      <ResumeDiffText richText value={item.title} diffs={fieldDiffs("title")} />
    </h3>
  );
  const subtitle = hasSubtitle ? (
    <p
      className={cn(
        "min-w-0 font-medium",
        layout === "inline" ? "wrap-anywhere" : "break-words",
        !item.subtitle && "resume-diff-empty-slot",
      )}
      style={{
        color: settings.bodyColor,
        fontSize: `${settings.bodyScale}em`,
      }}
    >
      <ResumeItemText
        diff={diff}
        fallbackDiffs={subtitleDiffs}
        parts={item.subtitleParts}
        value={item.subtitle}
      />
    </p>
  ) : null;
  const period = hasPeriod ? (
    <ResumeDiffText richText value={item.period} diffs={periodDiffs} />
  ) : null;
  const meta = hasMeta ? (
    <ResumeItemText
      diff={diff}
      fallbackDiffs={metaDiffs}
      parts={item.metaParts}
      value={item.meta}
    />
  ) : null;
  const hasMetadata = hasMeta || hasPeriod;

  if (layout === "stacked") {
    return (
      <div className="grid gap-1" data-resume-page-block="true">
        {title}
        {subtitle}
        {hasMetadata ? (
          <div
            className="resume-tone-muted flex flex-wrap gap-x-3 gap-y-1"
            style={{ fontSize: `${settings.metaScale}em` }}
          >
            {hasMeta ? (
              <span className={cn(!item.meta && "resume-diff-empty-slot")}>
                {meta}
              </span>
            ) : null}
            {period}
          </div>
        ) : null}
      </div>
    );
  }

  const isInline = layout === "inline";
  const isCompact = layout === "compact";
  const metadataClassName = cn(
    "resume-tone-muted",
    isCompact
      ? "whitespace-nowrap"
      : isInline
        ? "min-w-0 wrap-anywhere"
        : "min-w-0 break-words",
  );

  return (
    <div
      className={cn(
        "grid items-baseline gap-x-4 gap-y-1",
        isInline && "min-w-0",
        isInline && !hasPeriod
          ? "grid-cols-1"
          : isCompact
            ? "grid-cols-[minmax(0,1fr)_auto]"
            : "grid-cols-[minmax(0,1fr)_fit-content(45%)]",
      )}
      data-resume-page-block="true"
      style={isCompact ? undefined : { lineHeight: settings.bodyLineHeight }}
    >
      {isInline ? (
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
          {item.title || fieldDiffs("title").length > 0 ? title : null}
          {subtitle}
        </div>
      ) : (
        title
      )}
      {hasPeriod ? (
        <span
          className={cn(
            metadataClassName,
            "col-start-2 row-start-1 text-right",
            !item.period && "resume-diff-empty-slot",
          )}
          style={{ fontSize: `${settings.metaScale}em` }}
        >
          {period}
        </span>
      ) : null}
      {!isInline && hasSubtitle ? (
        <div className={cn("col-start-1 row-start-2", !isCompact && "min-w-0")}>
          {subtitle}
        </div>
      ) : null}
      {hasMeta ? (
        <span
          className={cn(
            metadataClassName,
            isInline ? "col-span-full" : "col-start-2 text-right",
            isInline || isCompact || hasPeriod ? "row-start-2" : "row-start-1",
            !item.meta && "resume-diff-empty-slot",
          )}
          style={{ fontSize: `${settings.metaScale}em` }}
        >
          {meta}
        </span>
      ) : null}
    </div>
  );
}
