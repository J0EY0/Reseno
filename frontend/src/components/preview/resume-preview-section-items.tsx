import type { ReactNode } from "react";

import {
  getDiffClassName,
  getDiffLabel,
  getRenderableItems,
} from "@/components/preview/resume-preview-model";
import type { AppMessages } from "@/i18n";
import type {
  RenderableResumeSection,
  RenderableSectionItem,
} from "@/lib/resume-sections";
import {
  isRichTextEmpty,
  sanitizeRichTextHtml,
  serializeHighlightsToHtml,
} from "@/lib/rich-text";
import { cn } from "@/lib/utils";
import type {
  ResumeDraftDiff,
  ResumeListItemLayout,
  ResumeTemplateLayout,
  ResumeTemplateSettings,
  ResumeTimelineItemLayout,
} from "@/types/resume";

interface SectionItemsProps {
  itemDiffById?: Map<string, ResumeDraftDiff>;
  items: RenderableSectionItem[];
  settings: ResumeTemplateSettings;
  t: AppMessages;
}

function TimelineItem({
  diff,
  item,
  layout,
  settings,
  t,
}: {
  diff?: ResumeDraftDiff;
  item: RenderableSectionItem;
  layout: ResumeTimelineItemLayout;
  settings: ResumeTemplateSettings;
  t: AppMessages;
}) {
  const highlightsHtml = serializeHighlightsToHtml(item.highlights);
  const title = (
    <h3
      className="min-w-0 break-words font-extrabold"
      style={{
        color: settings.bodyColor,
        fontSize: `${settings.itemTitleScale}em`,
      }}
    >
      {item.title}
    </h3>
  );
  const subtitle = item.subtitle ? (
    <p
      className={cn(
        "min-w-0 break-words font-medium",
        layout === "split" && "mt-1",
      )}
      style={{
        color: settings.bodyColor,
        fontSize: `${settings.bodyScale}em`,
      }}
    >
      {item.subtitle}
    </p>
  ) : null;
  const metadata = [item.meta, item.period].filter(Boolean);

  let heading: ReactNode;

  if (layout === "stacked") {
    heading = (
      <div className="grid gap-1">
        {title}
        {subtitle}
        {metadata.length > 0 ? (
          <div
            className="resume-tone-muted flex flex-wrap gap-x-3 gap-y-1"
            style={{ fontSize: `${settings.metaScale}em` }}
          >
            {metadata.map((value, index) => (
              <span key={`${value}-${index}`}>{value}</span>
            ))}
          </div>
        ) : null}
      </div>
    );
  } else if (layout === "compact") {
    heading = (
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4 gap-y-1">
        {title}
        {item.period ? (
          <span
            className="resume-tone-muted col-start-2 row-start-1 whitespace-nowrap text-right"
            style={{ fontSize: `${settings.metaScale}em` }}
          >
            {item.period}
          </span>
        ) : null}
        {item.subtitle ? (
          <div className="col-start-1 row-start-2">{subtitle}</div>
        ) : null}
        {item.meta ? (
          <span
            className="resume-tone-muted col-start-2 row-start-2 whitespace-nowrap text-right"
            style={{ fontSize: `${settings.metaScale}em` }}
          >
            {item.meta}
          </span>
        ) : null}
      </div>
    );
  } else {
    heading = (
      <div className="flex items-start justify-between gap-4 max-md:flex-col">
        <div className="min-w-0">
          {title}
          {subtitle}
        </div>
        {metadata.length > 0 ? (
          <div
            className="resume-tone-muted grid min-w-[170px] gap-1 text-right max-md:min-w-0 max-md:text-left"
            style={{ fontSize: `${settings.metaScale}em` }}
          >
            {item.meta ? <span>{item.meta}</span> : null}
            {item.period ? <span>{item.period}</span> : null}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <article
      className={cn("resume-item grid gap-2", getDiffClassName(diff))}
      data-resume-item-id={item.id}
      data-resume-diff-kind={diff?.kind}
      data-resume-diff-label={getDiffLabel(diff, t)}
    >
      {heading}

      {item.url ? (
        <p
          className="resume-tone-muted break-all"
          style={{ fontSize: `${settings.metaScale}em` }}
        >
          {item.url}
        </p>
      ) : null}

      {item.description ? (
        <p
          className="resume-tone-body"
          style={{
            fontSize: `${settings.bodyScale}em`,
            lineHeight: settings.bodyLineHeight,
          }}
        >
          {item.description}
        </p>
      ) : null}

      {!isRichTextEmpty(highlightsHtml) ? (
        <div
          className="resume-rich-text resume-tone-body"
          style={{
            fontSize: `${settings.bodyScale}em`,
            lineHeight: settings.bodyLineHeight,
          }}
          dangerouslySetInnerHTML={{
            __html: sanitizeRichTextHtml(highlightsHtml),
          }}
        />
      ) : null}
    </article>
  );
}

function TimelineItems({
  itemDiffById,
  items,
  layout,
  settings,
  t,
}: SectionItemsProps & { layout: ResumeTimelineItemLayout }) {
  return (
    <div
      className="grid"
      data-resume-items-list="true"
      style={{ gap: `${settings.itemGap}em` }}
    >
      {items.map((item) => (
        <TimelineItem
          key={item.id}
          item={item}
          t={t}
          settings={settings}
          diff={itemDiffById?.get(item.id)}
          layout={layout}
        />
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
  diff?: ResumeDraftDiff;
  item: RenderableSectionItem;
  layout: ResumeListItemLayout;
  settings: ResumeTemplateSettings;
  t: AppMessages;
}) {
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
          getDiffClassName(diff),
        )}
        data-resume-item-id={item.id}
        data-resume-diff-kind={diff?.kind}
        data-resume-diff-label={getDiffLabel(diff, t)}
        data-resume-list-layout={layout}
        style={{ color: settings.bodyColor }}
        dangerouslySetInnerHTML={{
          __html: sanitizeRichTextHtml(item.content),
        }}
      />
    </div>
  );
}

export function SectionItems({
  itemDiffById,
  items,
  layout,
  section,
  settings,
  t,
}: {
  itemDiffById?: Map<string, ResumeDraftDiff>;
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
      t={t}
      settings={settings}
      itemDiffById={itemDiffById}
      layout={layout.timelineItemLayout}
    />
  );
}
