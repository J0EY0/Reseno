import { getRichTextPlainText, joinInlineText } from "@/lib/rich-text";
import type {
  AchievementItem,
  EducationItem,
  ExperienceItem,
  ProjectItem,
  PublicationItem,
  ResumeSection,
  SectionItemByKind,
  SectionKind,
  SectionLayout,
  SimpleListItem,
} from "@/types/resume";

import { createId, isResumeNodeId } from "./resume-id";

export interface RenderableSectionItem {
  id: string;
  title: string;
  subtitle: string;
  subtitleParts?: RenderableItemTextPart[];
  meta: string;
  metaParts?: RenderableItemTextPart[];
  period: string;
  description: string;
  highlights: string[];
  content: string;
  url: string;
}

interface RenderableItemTextPart {
  field: string;
  value: string;
}

export interface RenderableResumeSection {
  id: string;
  kind: SectionKind;
  title: string;
  layout: SectionLayout;
  items: RenderableSectionItem[];
}

export const SECTION_RENDER_FAMILY: Record<SectionKind, SectionLayout> = {
  education: "timeline",
  experience: "timeline",
  project: "timeline",
  publication: "timeline",
  achievement: "timeline",
  simple_list: "list",
};

export const SECTION_ITEM_FIELDS = {
  education: [
    "school",
    "degree",
    "major",
    "gpa",
    "location",
    "period",
    "description",
    "highlights",
  ],
  experience: [
    "company",
    "position",
    "location",
    "period",
    "description",
    "highlights",
  ],
  project: [
    "name",
    "role",
    "techStack",
    "period",
    "url",
    "description",
    "highlights",
  ],
  publication: ["title", "authors", "venue", "date", "url", "description"],
  achievement: ["name", "issuer", "date", "url", "description"],
  simple_list: ["content"],
} as const satisfies Record<SectionKind, readonly string[]>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function hasExactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
) {
  const keys = Object.keys(value);
  return (
    keys.length === expected.length &&
    keys.every((key) => expected.includes(key))
  );
}

function hasStringFields(
  value: Record<string, unknown>,
  fields: readonly string[],
) {
  return fields.every((field) => typeof value[field] === "string");
}

export function isSectionItemForKind<K extends SectionKind>(
  kind: K,
  value: unknown,
): value is SectionItemByKind[K] {
  if (!isRecord(value) || !isResumeNodeId(value.id)) {
    return false;
  }

  const expectedKeys = ["id", ...SECTION_ITEM_FIELDS[kind]];
  if (!hasExactKeys(value, expectedKeys)) {
    return false;
  }

  switch (kind) {
    case "education":
      return (
        hasStringFields(value, [
          "school",
          "degree",
          "major",
          "gpa",
          "location",
          "period",
          "description",
        ]) &&
        Array.isArray(value.highlights) &&
        value.highlights.every((entry) => typeof entry === "string")
      );
    case "experience":
      return (
        hasStringFields(value, [
          "company",
          "position",
          "location",
          "period",
          "description",
        ]) &&
        Array.isArray(value.highlights) &&
        value.highlights.every((entry) => typeof entry === "string")
      );
    case "project":
      return (
        hasStringFields(value, [
          "name",
          "role",
          "period",
          "url",
          "description",
        ]) &&
        Array.isArray(value.techStack) &&
        value.techStack.every((entry) => typeof entry === "string") &&
        Array.isArray(value.highlights) &&
        value.highlights.every((entry) => typeof entry === "string")
      );
    case "publication":
      return hasStringFields(value, SECTION_ITEM_FIELDS.publication);
    case "achievement":
      return hasStringFields(value, [
        "name",
        "issuer",
        "date",
        "url",
        "description",
      ]);
    case "simple_list":
      return typeof value.content === "string";
  }
}

export function isCanonicalResumeSection(
  value: unknown,
): value is ResumeSection {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["id", "kind", "title", "items"]) ||
    !isResumeNodeId(value.id) ||
    typeof value.title !== "string" ||
    typeof value.kind !== "string" ||
    !Object.hasOwn(SECTION_ITEM_FIELDS, value.kind) ||
    !Array.isArray(value.items)
  ) {
    return false;
  }

  const kind = value.kind as SectionKind;
  if (kind === "simple_list" && value.items.length !== 1) {
    return false;
  }
  return value.items.every((item) => isSectionItemForKind(kind, item));
}

function createEducationItem(): EducationItem {
  return {
    id: createId("item"),
    school: "",
    degree: "",
    major: "",
    gpa: "",
    location: "",
    period: "",
    description: "",
    highlights: [],
  };
}

function createExperienceItem(): ExperienceItem {
  return {
    id: createId("item"),
    company: "",
    position: "",
    location: "",
    period: "",
    description: "",
    highlights: [],
  };
}

function createProjectItem(): ProjectItem {
  return {
    id: createId("item"),
    name: "",
    role: "",
    techStack: [],
    period: "",
    url: "",
    description: "",
    highlights: [],
  };
}

function createPublicationItem(): PublicationItem {
  return {
    id: createId("item"),
    title: "",
    authors: "",
    venue: "",
    date: "",
    url: "",
    description: "",
  };
}

function createAchievementItem(): AchievementItem {
  return {
    id: createId("item"),
    name: "",
    issuer: "",
    date: "",
    url: "",
    description: "",
  };
}

function createSimpleListItem(): SimpleListItem {
  return {
    id: createId("item"),
    content: "",
  };
}

export function createSectionItem<K extends SectionKind>(
  kind: K,
): SectionItemByKind[K] {
  // The cast stays inside this module so callers retain a correlated kind/item type.
  switch (kind) {
    case "education":
      return createEducationItem() as SectionItemByKind[K];
    case "experience":
      return createExperienceItem() as SectionItemByKind[K];
    case "project":
      return createProjectItem() as SectionItemByKind[K];
    case "publication":
      return createPublicationItem() as SectionItemByKind[K];
    case "achievement":
      return createAchievementItem() as SectionItemByKind[K];
    case "simple_list":
      return createSimpleListItem() as SectionItemByKind[K];
  }
}

export function createResumeSection(kind: SectionKind): ResumeSection {
  const id = createId("section");

  switch (kind) {
    case "education":
      return { id, kind, title: "", items: [createEducationItem()] };
    case "experience":
      return { id, kind, title: "", items: [createExperienceItem()] };
    case "project":
      return { id, kind, title: "", items: [createProjectItem()] };
    case "publication":
      return { id, kind, title: "", items: [createPublicationItem()] };
    case "achievement":
      return { id, kind, title: "", items: [createAchievementItem()] };
    case "simple_list":
      return { id, kind, title: "", items: [createSimpleListItem()] };
  }
}

function hasText(values: string[]) {
  return values.some((value) => getRichTextPlainText(value).trim());
}

export function hasSectionItemContent(
  kind: "education",
  item: EducationItem,
): boolean;
export function hasSectionItemContent(
  kind: "experience",
  item: ExperienceItem,
): boolean;
export function hasSectionItemContent(
  kind: "project",
  item: ProjectItem,
): boolean;
export function hasSectionItemContent(
  kind: "publication",
  item: PublicationItem,
): boolean;
export function hasSectionItemContent(
  kind: "achievement",
  item: AchievementItem,
): boolean;
export function hasSectionItemContent(
  kind: "simple_list",
  item: SimpleListItem,
): boolean;
export function hasSectionItemContent(
  kind: SectionKind,
  item: SectionItemByKind[SectionKind],
) {
  switch (kind) {
    case "education": {
      const value = item as EducationItem;
      return hasText([
        value.school,
        value.degree,
        value.major,
        value.gpa,
        value.location,
        value.period,
        value.description,
        ...value.highlights,
      ]);
    }
    case "experience": {
      const value = item as ExperienceItem;
      return hasText([
        value.company,
        value.position,
        value.location,
        value.period,
        value.description,
        ...value.highlights,
      ]);
    }
    case "project": {
      const value = item as ProjectItem;
      return hasText([
        value.name,
        value.role,
        ...value.techStack,
        value.period,
        value.url,
        value.description,
        ...value.highlights,
      ]);
    }
    case "publication": {
      const value = item as PublicationItem;
      return hasText(
        SECTION_ITEM_FIELDS.publication.map((field) => value[field]),
      );
    }
    case "achievement": {
      const value = item as AchievementItem;
      return hasText([
        value.name,
        value.issuer,
        value.date,
        value.url,
        value.description,
      ]);
    }
    case "simple_list":
      return hasText([(item as SimpleListItem).content]);
  }
}

export function hasSectionContent(section: ResumeSection) {
  switch (section.kind) {
    case "education":
      return section.items.some((item) =>
        hasSectionItemContent("education", item),
      );
    case "experience":
      return section.items.some((item) =>
        hasSectionItemContent("experience", item),
      );
    case "project":
      return section.items.some((item) =>
        hasSectionItemContent("project", item),
      );
    case "publication":
      return section.items.some((item) =>
        hasSectionItemContent("publication", item),
      );
    case "achievement":
      return section.items.some((item) =>
        hasSectionItemContent("achievement", item),
      );
    case "simple_list":
      return section.items.some((item) =>
        hasSectionItemContent("simple_list", item),
      );
  }
}

function createRenderableItem(
  item: Omit<RenderableSectionItem, "content" | "url"> &
    Partial<Pick<RenderableSectionItem, "content" | "url">>,
): RenderableSectionItem {
  return {
    content: "",
    url: "",
    ...item,
  };
}

export function projectResumeSection(
  section: ResumeSection,
): RenderableResumeSection {
  switch (section.kind) {
    case "education":
      return {
        ...section,
        layout: SECTION_RENDER_FAMILY.education,
        items: section.items.map((item) =>
          createRenderableItem({
            id: item.id,
            title: item.school,
            subtitle: [item.degree, item.major].filter(Boolean).join(" · "),
            subtitleParts: [
              { field: "degree", value: item.degree },
              { field: "major", value: item.major },
            ],
            meta: [item.gpa, item.location].filter(Boolean).join(" · "),
            metaParts: [
              { field: "gpa", value: item.gpa },
              { field: "location", value: item.location },
            ],
            period: item.period,
            description: item.description,
            highlights: item.highlights,
          }),
        ),
      };
    case "experience":
      return {
        ...section,
        layout: SECTION_RENDER_FAMILY.experience,
        items: section.items.map((item) =>
          createRenderableItem({
            id: item.id,
            title: item.company,
            subtitle: item.position,
            meta: item.location,
            period: item.period,
            description: item.description,
            highlights: item.highlights,
          }),
        ),
      };
    case "project":
      return {
        ...section,
        layout: SECTION_RENDER_FAMILY.project,
        items: section.items.map((item) =>
          createRenderableItem({
            id: item.id,
            title: item.name,
            subtitle: item.role,
            meta: joinInlineText(item.techStack, " · "),
            period: item.period,
            description: item.description,
            highlights: item.highlights,
            url: item.url,
          }),
        ),
      };
    case "publication":
      return {
        ...section,
        layout: SECTION_RENDER_FAMILY.publication,
        items: section.items.map((item) =>
          createRenderableItem({
            id: item.id,
            title: item.title,
            subtitle: item.authors,
            meta: item.venue,
            period: item.date,
            description: item.description,
            highlights: [],
            url: item.url,
          }),
        ),
      };
    case "achievement":
      return {
        ...section,
        layout: SECTION_RENDER_FAMILY.achievement,
        items: section.items.map((item) =>
          createRenderableItem({
            id: item.id,
            title: item.name,
            subtitle: item.issuer,
            meta: "",
            period: item.date,
            description: item.description,
            highlights: [],
            url: item.url,
          }),
        ),
      };
    case "simple_list":
      return {
        ...section,
        layout: SECTION_RENDER_FAMILY.simple_list,
        items: [
          createRenderableItem({
            id: section.items[0].id,
            title: "",
            subtitle: "",
            meta: "",
            period: "",
            description: "",
            highlights: [],
            content: section.items[0].content,
          }),
        ],
      };
  }
}

export function projectResumeSections(sections: ResumeSection[]) {
  return sections.map(projectResumeSection);
}
