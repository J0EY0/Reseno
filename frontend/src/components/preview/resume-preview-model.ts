import { useMemo } from "react";

import { createResumeDiffLookup } from "@/components/preview/resume-preview-diff-lookup";
import type { ResumeDiffLookup } from "@/components/preview/resume-preview-diffs";
import { createResumePreviewStyles } from "@/components/preview/resume-preview-styles";
import type { AppMessages } from "@/i18n";
import { projectResumeSections } from "@/lib/resume-sections";
import { isRichTextEmpty } from "@/lib/rich-text";
import { cn } from "@/lib/utils";
import type {
  RenderableResumeSection,
  RenderableSectionItem,
} from "@/lib/resume-sections";
import type {
  ResumeData,
  ResumeDraftDiff,
  ResumeFontFamily,
  ResumeTemplateDefinition,
} from "@/types/resume";

export const A4_WIDTH_MM = 210;
export const A4_HEIGHT_MM = 297;

export interface PaginatedResumeSection {
  section: RenderableResumeSection;
  items: RenderableSectionItem[];
  showTitle: boolean;
}

export interface ResumePreviewModel {
  contentFlowStyle: ReturnType<
    typeof createResumePreviewStyles
  >["contentFlowStyle"];
  diffLookup: ResumeDiffLookup;
  fontFamily: ResumeFontFamily;
  fontSize: number;
  fullPreviewSections: PaginatedResumeSection[];
  isSidebarLayout: boolean;
  layout: ResumeTemplateDefinition["layout"];
  pageStyle: ReturnType<typeof createResumePreviewStyles>["pageStyle"];
  resume: ResumeData;
  settings: ResumeTemplateDefinition["settings"];
  standardContentHeightMm: number;
  standardContentWidthMm: number;
  t: AppMessages;
  template: ResumeTemplateDefinition;
  visibleSections: RenderableResumeSection[];
}

const emptyDiffLookup: ResumeDiffLookup = {
  basicDiffByField: new Map(),
  deletedItemDiffsBySectionId: new Map(),
  deletedSectionDiffs: [],
  itemDiffById: new Map(),
  sectionDiffById: new Map(),
};

function hasRenderableItemContent(item: RenderableSectionItem) {
  return [
    item.title,
    item.subtitle,
    item.meta,
    item.period,
    item.description,
    item.content,
    item.url,
    ...item.highlights,
  ].some((value) => !isRichTextEmpty(value));
}

export function getRenderableItems(
  section: RenderableResumeSection,
) {
  return section.items.filter((item) =>
    section.layout === "list"
      ? !isRichTextEmpty(item.content)
      : hasRenderableItemContent(item),
  );
}

export function getResumeFallbackName(t: AppMessages) {
  return t.resumePreviewFallbackName;
}

export function getDiffClassName(diff?: ResumeDraftDiff) {
  return diff ? `resume-diff resume-diff--${diff.kind}` : undefined;
}

export function getDiffLabel(
  diff: ResumeDraftDiff | undefined,
  t: AppMessages,
) {
  if (!diff) {
    return undefined;
  }

  switch (diff.kind) {
    case "added":
      return t.agentDiffAdded;
    case "deleted":
      return t.agentDiffDeleted;
    case "moved":
      return t.agentDiffMoved;
    case "modified":
      return t.agentDiffModified;
  }
}

export function createResumePageClassName(
  model: ResumePreviewModel,
  thumbnail = false,
) {
  return cn(
    "resume-page",
    model.isSidebarLayout && "resume-page--sidebar",
    thumbnail && "resume-page--thumbnail",
    !model.isSidebarLayout &&
      model.template.preset === "modern" &&
      "resume-page--modern",
    !model.isSidebarLayout &&
      model.template.preset === "compact" &&
      "resume-page--compact",
  );
}

export function useResumePreviewModel({
  diffs,
  fontFamily,
  fontSize,
  resume,
  t,
  template,
}: {
  diffs?: ResumeDraftDiff[];
  fontFamily: ResumeFontFamily;
  fontSize: number;
  resume: ResumeData;
  t: AppMessages;
  template: ResumeTemplateDefinition;
}): ResumePreviewModel {
  // The rendered resume and its diff lookup form one presentation. Building
  // both in the same render prevents a transient frame without review marks
  // when the user moves between the aggregate and single-item views.
  const diffLookup = useMemo(
    () => (diffs?.length ? createResumeDiffLookup(diffs) : emptyDiffLookup),
    [diffs],
  );
  const projectedSections = useMemo(
    () => projectResumeSections(resume.sections),
    [resume.sections],
  );
  const visibleSections = useMemo(
    () =>
      projectedSections.filter(
        (section) =>
          getRenderableItems(section).length > 0,
      ),
    [projectedSections],
  );
  const fullPreviewSections = useMemo(
    () =>
      visibleSections.map((section) => ({
        section,
        items: getRenderableItems(section),
        showTitle: true,
      })),
    [visibleSections],
  );
  const settings = template.settings;
  const layout = template.layout;
  const isSidebarLayout = layout.basicInfo === "sidebar";
  const standardContentWidthMm = A4_WIDTH_MM - settings.pagePaddingX * 2;
  const standardContentHeightMm =
    A4_HEIGHT_MM - settings.pagePaddingTop - settings.pagePaddingBottom;
  const { contentFlowStyle, pageStyle } = useMemo(
    () =>
      createResumePreviewStyles({
        contentWidthMm: standardContentWidthMm,
        fontFamily,
        fontSize,
        isSidebarLayout,
        settings,
      }),
    [fontFamily, fontSize, isSidebarLayout, settings, standardContentWidthMm],
  );

  return useMemo(
    () => ({
      contentFlowStyle,
      diffLookup,
      fontFamily,
      fontSize,
      fullPreviewSections,
      isSidebarLayout,
      layout,
      pageStyle,
      resume,
      settings,
      standardContentHeightMm,
      standardContentWidthMm,
      t,
      template,
      visibleSections,
    }),
    [
      contentFlowStyle,
      diffLookup,
      fontFamily,
      fontSize,
      fullPreviewSections,
      isSidebarLayout,
      layout,
      pageStyle,
      resume,
      settings,
      standardContentHeightMm,
      standardContentWidthMm,
      t,
      template,
      visibleSections,
    ],
  );
}
