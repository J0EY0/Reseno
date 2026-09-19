import { Fragment, type ReactNode } from "react";

import { ResumeDiffBadge } from "@/components/preview/resume-preview-diff-badge";
import { ResumeDeletedDiffAnchor } from "@/components/preview/resume-preview-deleted-anchor";
import { interleaveDeletedDiffs } from "@/components/preview/resume-preview-deleted-placement";
import { ResumeDiffText } from "@/components/preview/resume-preview-diff-text";
import {
  getRenderableFieldDiffs,
  type ItemDiffLookup,
  type RenderableItemField,
} from "@/components/preview/resume-preview-diffs";
import { ResumeItemText } from "@/components/preview/resume-preview-item-text";
import {
  RichHighlights,
  RichListDiff,
} from "@/components/preview/resume-preview-rich-content";
import {
  getDiffClassName,
  getDiffLabel,
  getRenderableItems,
} from "@/components/preview/resume-preview-model";
import type { AppMessages } from "@/i18n";
import { createContactHref } from "@/lib/contact-links";
import type {
  RenderableResumeSection,
  RenderableSectionItem,
} from "@/lib/resume-sections";
import { isRichTextEmpty } from "@/lib/rich-text";
import { cn } from "@/lib/utils";
import type {
  ResumeDraftDiff,
  ResumeListItemLayout,
  SectionKind,
  ResumeTemplateLayout,
  ResumeTemplateSettings,
  ResumeTimelineItemLayout,
} from "@/types/resume";

interface SectionItemsProps {
  deletedItemDiffs?: ResumeDraftDiff[];
  itemDiffById?: Map<string, ItemDiffLookup>;
  items: RenderableSectionItem[];
  settings: ResumeTemplateSettings;
  t: AppMessages;
}

function hasTextSlot(
  value: string,
  fallbackDiffs: ResumeDraftDiff[],
  parts: RenderableSectionItem["subtitleParts"],
) {
  return Boolean(
    value || fallbackDiffs.length > 0 || parts?.some((part) => part.value),
  );
}

function TimelineItem({
  diff,
  enableContactLinks,
  item,
  kind,
  layout,
  settings,
  t,
}: {
  diff?: ItemDiffLookup;
  enableContactLinks: boolean;
  item: RenderableSectionItem;
  kind: SectionKind;
  layout: ResumeTimelineItemLayout;
  settings: ResumeTemplateSettings;
  t: AppMessages;
}) {
  const fieldDiffs = (field: RenderableItemField) =>
    getRenderableFieldDiffs(diff, kind, field);
  const structuralDiff = diff?.structuralDiff;
  const modifiedDiff = [...(diff?.fieldDiffByName.values() ?? [])].at(-1);
  const markerDiff = structuralDiff ?? modifiedDiff;
  const urlDiffs = fieldDiffs("url");
  const descriptionDiffs = fieldDiffs("description");
  const subtitleDiffs = fieldDiffs("subtitle");
  const metaDiffs = fieldDiffs("meta");
  const periodDiffs = fieldDiffs("period");
  const urlHref = createContactHref("url", item.url);
  const hasSubtitle = hasTextSlot(
    item.subtitle,
    subtitleDiffs,
    item.subtitleParts,
  );
  const hasMeta = hasTextSlot(item.meta, metaDiffs, item.metaParts);
  const hasPeriod = Boolean(item.period || periodDiffs.length > 0);
  const title = (
    <h3
      className="min-w-0 break-words font-extrabold"
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
        "min-w-0 break-words font-medium",
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
  const hasMetadata = hasMeta || hasPeriod;

  let heading: ReactNode;

  if (layout === "stacked") {
    heading = (
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
                <ResumeItemText
                  diff={diff}
                  fallbackDiffs={metaDiffs}
                  parts={item.metaParts}
                  value={item.meta}
                />
              </span>
            ) : null}
            {hasPeriod ? (
              <ResumeDiffText
                richText
                value={item.period}
                diffs={periodDiffs}
              />
            ) : null}
          </div>
        ) : null}
      </div>
    );
  } else if (layout === "compact") {
    heading = (
      <div
        className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4 gap-y-1"
        data-resume-page-block="true"
      >
        {title}
        {hasPeriod ? (
          <span
            className={cn(
              "resume-tone-muted col-start-2 row-start-1 whitespace-nowrap text-right",
              !item.period && "resume-diff-empty-slot",
            )}
            style={{ fontSize: `${settings.metaScale}em` }}
          >
            <ResumeDiffText richText value={item.period} diffs={periodDiffs} />
          </span>
        ) : null}
        {hasSubtitle ? (
          <div className="col-start-1 row-start-2">{subtitle}</div>
        ) : null}
        {hasMeta ? (
          <span
            className={cn(
              "resume-tone-muted col-start-2 row-start-2 whitespace-nowrap text-right",
              !item.meta && "resume-diff-empty-slot",
            )}
            style={{ fontSize: `${settings.metaScale}em` }}
          >
            <ResumeItemText
              diff={diff}
              fallbackDiffs={metaDiffs}
              parts={item.metaParts}
              value={item.meta}
            />
          </span>
        ) : null}
      </div>
    );
  } else {
    heading = (
      <div
        className="grid grid-cols-[minmax(0,1fr)_fit-content(45%)] items-baseline gap-x-4 gap-y-1"
        data-resume-page-block="true"
        style={{ lineHeight: settings.bodyLineHeight }}
      >
        {title}
        {hasPeriod ? (
          <span
            className={cn(
              "resume-tone-muted col-start-2 row-start-1 min-w-0 break-words text-right",
              !item.period && "resume-diff-empty-slot",
            )}
            style={{ fontSize: `${settings.metaScale}em` }}
          >
            <ResumeDiffText richText value={item.period} diffs={periodDiffs} />
          </span>
        ) : null}
        {hasSubtitle ? (
          <div className="col-start-1 row-start-2 min-w-0">{subtitle}</div>
        ) : null}
        {hasMeta ? (
          <span
            className={cn(
              "resume-tone-muted col-start-2 min-w-0 break-words text-right",
              hasPeriod ? "row-start-2" : "row-start-1",
              !item.meta && "resume-diff-empty-slot",
            )}
            style={{ fontSize: `${settings.metaScale}em` }}
          >
            <ResumeItemText
              diff={diff}
              fallbackDiffs={metaDiffs}
              parts={item.metaParts}
              value={item.meta}
            />
          </span>
        ) : null}
      </div>
    );
  }

  return (
    <article
      className={cn(
        "resume-item relative grid gap-[0.375em]",
        getDiffClassName(structuralDiff),
        markerDiff && "resume-diff-label-host",
      )}
      data-resume-item-id={item.id}
      data-resume-diff-kind={markerDiff?.kind}
      data-resume-diff-label={getDiffLabel(markerDiff, t)}
      data-resume-diff-path={structuralDiff?.path}
    >
      <ResumeDiffBadge diff={markerDiff} t={t} />
      {heading}

      {item.url || urlDiffs.length > 0 ? (
        <p
          className={cn(
            "resume-tone-muted break-all",
            !item.url && "resume-diff-empty-slot",
          )}
          style={{ fontSize: `${settings.metaScale}em` }}
        >
          {enableContactLinks && urlHref && urlDiffs.length === 0 ? (
            <a
              href={urlHref}
              className="text-inherit no-underline [font-kerning:none] hover:underline"
              target="_blank"
              rel="noreferrer noopener"
            >
              <ResumeDiffText value={item.url} diffs={urlDiffs} />
            </a>
          ) : (
            <ResumeDiffText value={item.url} diffs={urlDiffs} />
          )}
        </p>
      ) : null}

      {item.description || descriptionDiffs.length > 0 ? (
        <p
          className={cn(
            "resume-tone-body",
            !item.description && "resume-diff-empty-slot",
          )}
          style={{
            fontSize: `${settings.bodyScale}em`,
            lineHeight: settings.bodyLineHeight,
          }}
        >
          <ResumeDiffText
            richText
            value={item.description}
            diffs={descriptionDiffs}
          />
        </p>
      ) : null}

      {item.highlights.some((highlight) => !isRichTextEmpty(highlight)) ||
      fieldDiffs("highlights").length > 0 ? (
        <div
          className="resume-rich-text resume-tone-body"
          style={{
            fontSize: `${settings.bodyScale}em`,
            lineHeight: settings.bodyLineHeight,
          }}
        >
          <RichHighlights
            highlights={item.highlights}
            diffs={fieldDiffs("highlights")}
          />
        </div>
      ) : null}
    </article>
  );
}

function TimelineItems({
  deletedItemDiffs,
  enableContactLinks,
  itemDiffById,
  items,
  kind,
  layout,
  settings,
  t,
}: SectionItemsProps & {
  enableContactLinks: boolean;
  kind: SectionKind;
  layout: ResumeTimelineItemLayout;
}) {
  const deleted = interleaveDeletedDiffs(items, deletedItemDiffs ?? []);

  return (
    <div
      className="relative grid"
      data-resume-items-list="true"
      style={{ gap: `${settings.itemGap}em` }}
    >
      {items.map((item) => (
        <Fragment key={item.id}>
          {(deleted.beforeById.get(item.id) ?? []).map((diff) => (
            <ResumeDeletedDiffAnchor diff={diff} key={diff.id} t={t} />
          ))}
          <TimelineItem
            item={item}
            enableContactLinks={enableContactLinks}
            kind={kind}
            t={t}
            settings={settings}
            diff={itemDiffById?.get(item.id)}
            layout={layout}
          />
          {(deleted.afterById.get(item.id) ?? []).map((diff) => (
            <ResumeDeletedDiffAnchor diff={diff} key={diff.id} t={t} />
          ))}
        </Fragment>
      ))}
      {deleted.unplaced.map((diff) => (
        <ResumeDeletedDiffAnchor diff={diff} key={diff.id} t={t} />
      ))}
    </div>
  );
}

function SimpleListContent({
  diff,
  item,
  layout,
  settings,
  t,
}: {
  diff?: ItemDiffLookup;
  item: RenderableSectionItem;
  layout: ResumeListItemLayout;
  settings: ResumeTemplateSettings;
  t: AppMessages;
}) {
  const structuralDiff = diff?.structuralDiff;
  const contentDiffs = getRenderableFieldDiffs(diff, "simple_list", "content");
  const markerDiff = structuralDiff ?? contentDiffs.at(-1);
  return (
    <div
      className="resume-tone-body"
      data-resume-items-list="true"
      style={{
        fontSize: `${settings.bodyScale}em`,
        lineHeight: settings.bodyLineHeight,
      }}
    >
      <div
        className={cn(
          "resume-item resume-rich-text min-w-0",
          getDiffClassName(structuralDiff),
          markerDiff && "resume-diff-label-host",
        )}
        data-resume-item-id={item.id}
        data-resume-diff-kind={markerDiff?.kind}
        data-resume-diff-label={getDiffLabel(markerDiff, t)}
        data-resume-diff-path={structuralDiff?.path}
        data-resume-list-layout={layout}
        style={{ color: settings.bodyColor }}
      >
        <ResumeDiffBadge diff={markerDiff} t={t} />
        <RichListDiff html={item.content} diffs={contentDiffs} />
      </div>
    </div>
  );
}

export function SectionItems({
  deletedItemDiffs,
  enableContactLinks,
  itemDiffById,
  items,
  layout,
  section,
  settings,
  t,
}: {
  enableContactLinks: boolean;
  deletedItemDiffs?: ResumeDraftDiff[];
  itemDiffById?: Map<string, ItemDiffLookup>;
  items?: RenderableSectionItem[];
  layout: ResumeTemplateLayout;
  section: RenderableResumeSection;
  settings: ResumeTemplateSettings;
  t: AppMessages;
}) {
  const visibleItems = items ?? getRenderableItems(section);

  if (section.kind === "simple_list") {
    const item = visibleItems[0];
    if (!item) {
      return null;
    }

    return (
      <SimpleListContent
        item={item}
        t={t}
        settings={settings}
        diff={itemDiffById?.get(item.id)}
        layout={layout.listItemLayout}
      />
    );
  }

  return (
    <TimelineItems
      items={visibleItems}
      enableContactLinks={enableContactLinks}
      kind={section.kind}
      t={t}
      settings={settings}
      itemDiffById={itemDiffById}
      layout={layout.timelineItemLayout}
      deletedItemDiffs={deletedItemDiffs}
    />
  );
}
