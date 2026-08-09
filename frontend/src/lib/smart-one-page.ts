import { resumeFontSizeOptions } from "@/lib/templates";
import type {
  ResumeTemplateSettings,
  ResumeTemplateSettingsOverrides,
  ResumeTypographySettings,
} from "@/types/resume";

const minimumFontSize = 12;
const layoutLevels = [
  {
    pagePaddingDelta: 2,
    sectionGap: 1,
    itemGap: 0.7,
    bodyLineHeight: 1.55,
  },
  {
    pagePaddingDelta: 3,
    sectionGap: 0.9,
    itemGap: 0.6,
    bodyLineHeight: 1.48,
    sectionTitleScale: 1.12,
  },
  {
    pagePaddingDelta: 4,
    sectionGap: 0.8,
    itemGap: 0.5,
    bodyLineHeight: 1.42,
    sectionTitleScale: 1,
    itemTitleScale: 0.96,
    metaScale: 0.86,
  },
  {
    pagePaddingDelta: 5,
    sectionGap: 0.8,
    itemGap: 0.4,
    bodyLineHeight: 1.4,
    nameScale: 1.85,
    sectionTitleScale: 0.9,
    itemTitleScale: 0.92,
    metaScale: 0.82,
    bodyScale: 0.9,
  },
] satisfies Array<{
  pagePaddingDelta: number;
  sectionGap: number;
  itemGap: number;
  bodyLineHeight: number;
  nameScale?: number;
  sectionTitleScale?: number;
  itemTitleScale?: number;
  metaScale?: number;
  bodyScale?: number;
}>;

export interface SmartOnePageStyleSnapshot {
  typography: ResumeTypographySettings;
  templateSettings: ResumeTemplateSettingsOverrides | null;
}

interface SmartOnePageAdapter {
  applyStyle: (snapshot: SmartOnePageStyleSnapshot) => void;
  measurePageCount: () => Promise<number>;
}

export type SmartOnePageResult =
  | { status: "already-one-page" }
  | { status: "applied"; previous: SmartOnePageStyleSnapshot }
  | { status: "no-fit" };

function getNextSmallerFontSize(fontSize: number) {
  const smallerSizes = resumeFontSizeOptions.filter((size) => size < fontSize);

  return smallerSizes.at(-1) ?? fontSize;
}

function compactNumber(current: number, target: number | undefined, min: number) {
  return Number(Math.max(min, Math.min(current, target ?? current)).toFixed(2));
}

function compactPagePadding(current: number, delta: number) {
  return Math.max(8, current - delta);
}

function createSettingsCandidate(
  settings: ResumeTemplateSettings,
  level: (typeof layoutLevels)[number],
): ResumeTemplateSettings {
  return {
    ...settings,
    pagePaddingTop: compactPagePadding(settings.pagePaddingTop, level.pagePaddingDelta),
    pagePaddingX: compactPagePadding(settings.pagePaddingX, level.pagePaddingDelta),
    pagePaddingBottom: compactPagePadding(
      settings.pagePaddingBottom,
      level.pagePaddingDelta,
    ),
    sectionGap: compactNumber(settings.sectionGap, level.sectionGap, 0.8),
    itemGap: compactNumber(settings.itemGap, level.itemGap, 0.4),
    bodyLineHeight: compactNumber(
      settings.bodyLineHeight,
      level.bodyLineHeight,
      1.4,
    ),
    nameScale: compactNumber(settings.nameScale, level.nameScale, 1.6),
    sectionTitleScale: compactNumber(
      settings.sectionTitleScale,
      level.sectionTitleScale,
      0.75,
    ),
    itemTitleScale: compactNumber(
      settings.itemTitleScale,
      level.itemTitleScale,
      0.85,
    ),
    metaScale: compactNumber(settings.metaScale, level.metaScale, 0.75),
    bodyScale: compactNumber(settings.bodyScale, level.bodyScale, 0.85),
  };
}

function areSnapshotsEqual(
  left: SmartOnePageStyleSnapshot,
  right: SmartOnePageStyleSnapshot,
) {
  return (
    left.typography.fontFamily === right.typography.fontFamily &&
    left.typography.fontSize === right.typography.fontSize &&
    JSON.stringify(left.templateSettings) === JSON.stringify(right.templateSettings)
  );
}

function createCandidates(
  typography: ResumeTypographySettings,
  settings: ResumeTemplateSettings,
) {
  const candidates: SmartOnePageStyleSnapshot[] = [];
  let fontSize = typography.fontSize;

  layoutLevels.forEach((level, index) => {
    if (index > 0) {
      fontSize = Math.max(minimumFontSize, getNextSmallerFontSize(fontSize));
    }

    candidates.push({
      typography: { ...typography, fontSize },
      templateSettings: createSettingsCandidate(settings, level),
    });
  });

  const strongestLevel = layoutLevels[layoutLevels.length - 1];

  while (fontSize > minimumFontSize) {
    fontSize = Math.max(minimumFontSize, getNextSmallerFontSize(fontSize));
    candidates.push({
      typography: { ...typography, fontSize },
      templateSettings: createSettingsCandidate(settings, strongestLevel),
    });
  }

  return candidates.filter((candidate, index, allCandidates) =>
    allCandidates.findIndex((item) => areSnapshotsEqual(item, candidate)) === index,
  );
}

export async function fitResumeToOnePage(
  current: SmartOnePageStyleSnapshot,
  effectiveSettings: ResumeTemplateSettings,
  adapter: SmartOnePageAdapter,
): Promise<SmartOnePageResult> {
  if ((await adapter.measurePageCount()) <= 1) {
    return { status: "already-one-page" };
  }

  const effectiveCurrent = {
    typography: current.typography,
    templateSettings: effectiveSettings,
  } satisfies SmartOnePageStyleSnapshot;
  const candidates = createCandidates(
    current.typography,
    effectiveSettings,
  ).filter((candidate) => !areSnapshotsEqual(candidate, effectiveCurrent));

  for (const candidate of candidates) {
    adapter.applyStyle(candidate);

    // React commits the candidate before the adapter measures the paginated DOM.
    if ((await adapter.measurePageCount()) <= 1) {
      return { status: "applied", previous: current };
    }
  }

  adapter.applyStyle(current);
  return { status: "no-fit" };
}
