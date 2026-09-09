import type { GeneratedBuiltinTemplateId } from "@/lib/template-presets.generated";

export const SECTION_KINDS = [
  "education",
  "experience",
  "project",
  "publication",
  "achievement",
  "simple_list",
] as const;
export type SectionKind = (typeof SECTION_KINDS)[number];
export type SectionLayout = "timeline" | "list";
export type ResumeTimelineItemLayout = "split" | "stacked" | "compact";
export type ResumeListItemLayout = "list" | "inline" | "columns";
export type ResumeFontFamily =
  "inter" | "noto_sans_sc" | "serif" | "times" | "plex";
export type ThemeMode = "light" | "dark" | "system";
export type BuiltinResumeTemplateId = GeneratedBuiltinTemplateId;
export type ResumeBasicInfoLayout =
  "centered" | "left" | "split" | "profile" | "sidebar";
export type ResumeAvatarPosition = "none" | "right" | "left" | "center";
export type ResumeAvatarShape = "rounded" | "circle" | "square";
export type ResumeSectionTemplateStyle =
  "ruled" | "underlined" | "boxed" | "accent" | "plain" | "band";
export type ResumeTemplateImageFit = "contain" | "cover";
export type ResumeTemplateId = string;
export type WorkspaceView =
  "resume" | "templates" | "trash" | "models" | "settings";
export type AgentResponseLanguage = "follow" | "zh" | "en";
export type AgentBehaviorMode = "balanced" | "strict" | "aggressive";
export type AgentConfirmationMode = "always" | "suggestOnly";
export type ContactFieldType = "email" | "phone" | "url" | "text";

export interface CustomField {
  id: string;
  type: ContactFieldType;
  label: string;
  value: string;
}

export interface ResumeBasicInfo {
  name: string;
  headline: string;
  phone: string;
  email: string;
  location: string;
  avatar: string;
  summary: string;
  customFields: CustomField[];
}

export interface EducationItem {
  id: string;
  school: string;
  degree: string;
  major: string;
  gpa: string;
  location: string;
  period: string;
  description: string;
  highlights: string[];
}

export interface ExperienceItem {
  id: string;
  company: string;
  position: string;
  location: string;
  period: string;
  description: string;
  highlights: string[];
}

export interface ProjectItem {
  id: string;
  name: string;
  role: string;
  techStack: string[];
  period: string;
  url: string;
  description: string;
  highlights: string[];
}

export interface PublicationItem {
  id: string;
  title: string;
  authors: string;
  venue: string;
  date: string;
  url: string;
  description: string;
}

export interface AchievementItem {
  id: string;
  name: string;
  issuer: string;
  date: string;
  url: string;
  description: string;
}

export interface SimpleListItem {
  id: string;
  content: string;
}

export interface SectionItemByKind {
  education: EducationItem;
  experience: ExperienceItem;
  project: ProjectItem;
  publication: PublicationItem;
  achievement: AchievementItem;
  simple_list: SimpleListItem;
}

export type ResumeSectionItem = SectionItemByKind[SectionKind];

// A simple-list section owns one rich-text document. Its visible bullets live
// inside `content`, so they keep one stable item ID for autosave and Agent diffs.
type SectionItemsByKind<K extends SectionKind> = K extends "simple_list"
  ? [SectionItemByKind[K]]
  : SectionItemByKind[K][];

export type ResumeSectionOf<K extends SectionKind> = {
  id: string;
  kind: K;
  title: string;
  items: SectionItemsByKind<K>;
};

export type ResumeSection = {
  [K in SectionKind]: ResumeSectionOf<K>;
}[SectionKind];

export interface ResumeData {
  schemaVersion: 2;
  basic: ResumeBasicInfo;
  sections: ResumeSection[];
}

export type DocumentLocale = "zh" | "en";

type ResumeDraftDiffKind = "added" | "modified" | "deleted" | "moved";

export interface ResumeDraftDiff {
  id: string;
  operationId: string;
  path: string;
  kind: ResumeDraftDiffKind;
  label: string;
  sectionId?: string;
  itemId?: string;
  beforePreviousId?: string;
  beforeNextId?: string;
  before?: unknown;
  after?: unknown;
}

export interface ResumeTypographySettings {
  fontFamily: ResumeFontFamily;
  fontSize: number;
}

export interface ResumeTemplateSettings {
  pagePaddingTop: number;
  pagePaddingX: number;
  pagePaddingBottom: number;
  sectionGap: number;
  itemGap: number;
  bodyLineHeight: number;
  nameScale: number;
  sectionTitleScale: number;
  itemTitleScale: number;
  metaScale: number;
  bodyScale: number;
  pageBackground: string;
  surfaceColor: string;
  headingColor: string;
  bodyColor: string;
  mutedColor: string;
  dividerColor: string;
  dividerThickness: number;
}

export type ResumeTemplateSettingsOverrides = Partial<ResumeTemplateSettings>;

export interface ResumeTemplateImageElement {
  id: string;
  name: string;
  src: string;
  alt: string;
  x: number;
  y: number;
  width: number;
  height: number;
  opacity: number;
  borderWidth: number;
  borderColor: string;
  borderRadius: number;
  objectFit: ResumeTemplateImageFit;
  visible: boolean;
}

export interface ResumeTemplateLayout {
  basicInfo: ResumeBasicInfoLayout;
  section: ResumeSectionTemplateStyle;
  // Item layouts follow the section's semantic layout family. New section
  // kinds therefore inherit template behavior without a kind-specific map.
  timelineItemLayout: ResumeTimelineItemLayout;
  listItemLayout: ResumeListItemLayout;
  avatarPosition: ResumeAvatarPosition;
  avatarShape: ResumeAvatarShape;
  avatarWidth: number;
  avatarHeight: number;
  avatarOffsetX: number;
  avatarOffsetY: number;
  avatarBorderWidth: number;
  avatarBorderColor: string;
  images: ResumeTemplateImageElement[];
}

export interface ResumeTemplateDefinition {
  id: ResumeTemplateId;
  preset: BuiltinResumeTemplateId;
  name: string;
  description: string;
  layout: ResumeTemplateLayout;
  typography: ResumeTypographySettings;
  settings: ResumeTemplateSettings;
  updatedAt: string;
  isBuiltIn: boolean;
}

export type ThinkingMode = "auto" | "off";

export interface ModelConfig {
  id: string;
  provider: string;
  providerLabel: string;
  iconProvider: string;
  providerKind: "cloud" | "local" | "custom";
  apiFamily:
    | "openai_responses"
    | "openai_compatible_chat"
    | "anthropic_messages"
    | "google_gemini";
  nickname: string;
  apiKeyPreview: string;
  model: string;
  apiUrl: string;
  temperature: number | null;
  topP: number | null;
  maxTokens: number | null;
  contextWindowTokens: number;
  supportsImage: boolean;
  supportsThinking: boolean;
  thinkingMode: ThinkingMode;
  availableThinkingModes: ThinkingMode[];
  supportsTools: boolean;
  supportsStreaming: boolean;
}

export interface AgentSettings {
  defaultModelConfigId: string;
  responseLanguage: AgentResponseLanguage;
  behaviorMode: AgentBehaviorMode;
  confirmationMode: AgentConfirmationMode;
}

export interface ResumeWorkspaceItem {
  id: string;
  title: string;
  updatedAt: string;
  documentLocale: DocumentLocale;
  resume: ResumeData;
  jobBrief: string;
  typography: ResumeTypographySettings;
  template: ResumeTemplateId;
  templateSettings: ResumeTemplateSettingsOverrides | null;
}

export type DefaultTemplateIds = Record<DocumentLocale, ResumeTemplateId>;

export interface DeletedResumeWorkspaceItem extends ResumeWorkspaceItem {
  deletedAt: string;
}

export type ResumeTemplateUpdate =
  | Partial<ResumeTemplateDefinition>
  | ((current: ResumeTemplateDefinition) => Partial<ResumeTemplateDefinition>);

export interface DeletedResumeTemplateDefinition extends ResumeTemplateDefinition {
  deletedAt: string;
}
