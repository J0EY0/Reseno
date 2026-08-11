import { type ReactNode } from "react";

import { ResumeDiffText } from "@/components/preview/resume-preview-diff-text";
import type {
  ItemDiffLookup,
  SectionDiffLookup,
} from "@/components/preview/resume-preview-diffs";
import {
  getDiffClassName,
  getDiffLabel,
  getRenderableItems,
  type PaginatedResumeSection,
} from "@/components/preview/resume-preview-model";
import { SectionItems } from "@/components/preview/resume-preview-section-items";
import type { AppMessages } from "@/i18n";
import { getSectionTitle } from "@/lib/resume";
import type {
  RenderableResumeSection,
  RenderableSectionItem,
} from "@/lib/resume-sections";
import { cn } from "@/lib/utils";
import type {
  ResumeTemplateLayout,
  ResumeTemplateSettings,
} from "@/types/resume";

function RuledSectionTitle({
  children,
  settings,
}: {
  children: ReactNode;
  settings: ResumeTemplateSettings;
}) {
  return (
    <div className="flex items-center gap-4">
      <h2
        className="shrink-0 font-extrabold"
        style={{
          color: settings.headingColor,
          fontSize: `${settings.sectionTitleScale}em`,
        }}
      >
        {children}
      </h2>
      <div
        className="flex-1"
        style={{
          height: `${settings.dividerThickness}px`,
          backgroundColor: settings.dividerColor,
        }}
      />
    </div>
  );
}

function AccentSectionTitle({
  children,
  isSidebarLayout,
  settings,
}: {
  children: ReactNode;
  isSidebarLayout: boolean;
  settings: ResumeTemplateSettings;
}) {
  if (isSidebarLayout) {
    return <RuledSectionTitle settings={settings}>{children}</RuledSectionTitle>;
  }

  return (
    <div className="relative flex items-center justify-center">
      <div
        className="absolute inset-x-0 top-1/2"
        style={{
          height: `${settings.dividerThickness}px`,
          backgroundColor: settings.dividerColor,
        }}
      />
      <h2
        className="relative px-4 text-center font-extrabold tracking-[0.18em]"
        style={{
          color: settings.headingColor,
          backgroundColor: settings.pageBackground,
          fontSize: `${settings.sectionTitleScale}em`,
        }}
      >
        {children}
      </h2>
    </div>
  );
}

interface SectionBlockProps {
  breakBeforeOffset?: number;
  diff?: SectionDiffLookup;
  isSidebarLayout: boolean;
  itemDiffById?: Map<string, ItemDiffLookup>;
  items?: RenderableSectionItem[];
  layout: ResumeTemplateLayout;
  section: RenderableResumeSection;
  settings: ResumeTemplateSettings;
  showTitle?: boolean;
  t: AppMessages;
}

function SectionBlock({
  breakBeforeOffset = 0,
  diff,
  isSidebarLayout,
  itemDiffById,
  items,
  layout,
  section,
  settings,
  showTitle = true,
  t,
}: SectionBlockProps) {
  const title = getSectionTitle(section, t);
  const allVisibleItems = getRenderableItems(section);
  const visibleItems = items ?? allVisibleItems;
  const structuralDiff = diff?.structuralDiff;
  const titleDiff = showTitle ? diff?.titleDiff : undefined;
  const markerDiff = structuralDiff ?? titleDiff;
  const sectionClassName = structuralDiff
    ? getDiffClassName(structuralDiff)
    : titleDiff
      ? "resume-diff-anchor"
      : undefined;
  const renderedTitle = (
    <ResumeDiffText
      value={title}
      diffs={titleDiff ? [titleDiff] : []}
    />
  );
  const sectionStyle =
    breakBeforeOffset > 0 ? { marginTop: breakBeforeOffset } : undefined;

  if (layout.section === "boxed") {
    return (
      <section
        className={cn(
          "resume-section relative overflow-hidden border",
          sectionClassName,
        )}
        data-resume-section-id={section.id}
        data-resume-diff-kind={markerDiff?.kind}
        data-resume-diff-label={getDiffLabel(markerDiff, t)}
        data-resume-section-layout={layout.section}
        style={{ ...sectionStyle, borderColor: settings.dividerColor }}
      >
        {showTitle ? (
          <div
            className="resume-section-header border-b px-4 py-2"
            data-resume-section-header="true"
            style={{
              backgroundColor: settings.surfaceColor,
              borderColor: settings.dividerColor,
            }}
          >
            <h2
              className="font-extrabold"
              style={{
                color: settings.headingColor,
                fontSize: `${settings.sectionTitleScale}em`,
              }}
            >
              {renderedTitle}
            </h2>
          </div>
        ) : null}
        <div className="p-4">
          <SectionItems
            section={section}
            t={t}
            settings={settings}
            layout={layout}
            items={visibleItems}
            itemDiffById={itemDiffById}
          />
        </div>
      </section>
    );
  }

  if (layout.section === "band") {
    return (
      <section
        className={cn("resume-section relative", sectionClassName)}
        data-resume-section-id={section.id}
        data-resume-diff-kind={markerDiff?.kind}
        data-resume-diff-label={getDiffLabel(markerDiff, t)}
        data-resume-section-layout={layout.section}
        style={sectionStyle}
      >
        {showTitle ? (
          <div
            className="resume-section-header rounded-sm px-3 py-1.5"
            data-resume-section-header="true"
            style={{ backgroundColor: settings.surfaceColor }}
          >
            <h2
              className="font-extrabold"
              style={{
                color: settings.headingColor,
                fontSize: `${settings.sectionTitleScale}em`,
              }}
            >
              {renderedTitle}
            </h2>
          </div>
        ) : null}
        <div className={showTitle ? "mt-3" : undefined}>
          <SectionItems
            section={section}
            t={t}
            settings={settings}
            layout={layout}
            items={visibleItems}
            itemDiffById={itemDiffById}
          />
        </div>
      </section>
    );
  }

  return (
    <section
      className={cn("resume-section relative", sectionClassName)}
      data-resume-section-id={section.id}
      data-resume-diff-kind={markerDiff?.kind}
      data-resume-diff-label={getDiffLabel(markerDiff, t)}
      data-resume-section-layout={layout.section}
      style={sectionStyle}
    >
      {showTitle ? (
        <div className="resume-section-header" data-resume-section-header="true">
          {layout.section === "plain" ? (
            <h2
              className="font-extrabold"
              style={{
                color: settings.headingColor,
                fontSize: `${settings.sectionTitleScale}em`,
              }}
            >
              {renderedTitle}
            </h2>
          ) : layout.section === "accent" ? (
            <AccentSectionTitle
              settings={settings}
              isSidebarLayout={isSidebarLayout}
            >
              {renderedTitle}
            </AccentSectionTitle>
          ) : (
            <RuledSectionTitle settings={settings}>
              {renderedTitle}
            </RuledSectionTitle>
          )}
        </div>
      ) : null}
      <div className={showTitle ? "mt-3" : undefined}>
        <SectionItems
          section={section}
          t={t}
          settings={settings}
          layout={layout}
          items={visibleItems}
          itemDiffById={itemDiffById}
        />
      </div>
    </section>
  );
}

export function SectionsList({
  breakBeforeSectionSpacers,
  className,
  isSidebarLayout,
  itemDiffById,
  layout,
  sectionDiffById,
  sections,
  settings,
  t,
}: {
  breakBeforeSectionSpacers?: Record<string, number>;
  className?: string;
  isSidebarLayout: boolean;
  itemDiffById?: Map<string, ItemDiffLookup>;
  layout: ResumeTemplateLayout;
  sectionDiffById?: Map<string, SectionDiffLookup>;
  sections: PaginatedResumeSection[];
  settings: ResumeTemplateSettings;
  t: AppMessages;
}) {
  return (
    <div
      className={cn("relative grid", className)}
      data-resume-sections-list="true"
      style={{ gap: `${settings.sectionGap}em` }}
    >
      {sections.map((section) => (
        <SectionBlock
          key={`${section.section.id}-${section.showTitle ? "title" : "continue"}-${section.items
            .map((item) => item.id)
            .join("-")}`}
          section={section.section}
          items={section.items}
          showTitle={section.showTitle}
          breakBeforeOffset={
            breakBeforeSectionSpacers?.[section.section.id] ?? 0
          }
          t={t}
          settings={settings}
          layout={layout}
          isSidebarLayout={isSidebarLayout}
          diff={sectionDiffById?.get(section.section.id)}
          itemDiffById={itemDiffById}
        />
      ))}
    </div>
  );
}
