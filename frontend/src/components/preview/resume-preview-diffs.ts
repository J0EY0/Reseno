import type { RenderableSectionItem } from "@/lib/resume-sections";
import type {
  ResumeDraftDiff,
  SectionKind,
} from "@/types/resume";

export type RenderableItemField = Exclude<
  keyof RenderableSectionItem,
  "id" | "metaParts" | "subtitleParts"
>;

export interface ItemDiffLookup {
  fieldDiffByName: Map<string, ResumeDraftDiff>;
  structuralDiff?: ResumeDraftDiff;
}

export interface SectionDiffLookup {
  structuralDiff?: ResumeDraftDiff;
  titleDiff?: ResumeDraftDiff;
}

export interface ResumeDiffLookup {
  basicDiffByField: Map<string, ResumeDraftDiff>;
  itemDiffById: Map<string, ItemDiffLookup>;
  sectionDiffById: Map<string, SectionDiffLookup>;
}

const renderFields: Record<
  SectionKind,
  Partial<Record<RenderableItemField, string>>
> = {
  education: {
    title: "school",
    subtitle: "degree major",
    meta: "gpa location",
    period: "period",
    description: "description",
    highlights: "highlights",
  },
  experience: {
    title: "company",
    subtitle: "position",
    meta: "location",
    period: "period",
    description: "description",
    highlights: "highlights",
  },
  project: {
    title: "name",
    subtitle: "role",
    meta: "techStack",
    period: "period",
    description: "description",
    highlights: "highlights",
    url: "url",
  },
  achievement: {
    title: "name",
    subtitle: "issuer",
    period: "date",
    description: "description",
    url: "url",
  },
  simple_list: {
    content: "content",
  },
};

export function getRenderableFieldDiffs(
  lookup: ItemDiffLookup | undefined,
  kind: SectionKind,
  field: RenderableItemField,
) {
  if (!lookup || lookup.structuralDiff?.kind === "added") {
    return [];
  }

  return (renderFields[kind][field]?.split(" ") ?? [])
    .map((name) => lookup.fieldDiffByName.get(name))
    .filter(Boolean) as ResumeDraftDiff[];
}

export function getCanonicalItemFieldDiffs(
  lookup: ItemDiffLookup | undefined,
  field: string,
) {
  if (!lookup || lookup.structuralDiff?.kind === "added") {
    return [];
  }

  const diff = lookup.fieldDiffByName.get(field);
  return diff ? [diff] : [];
}
