export type SectionKind =
  | 'education'
  | 'work'
  | 'internship'
  | 'project'
  | 'skills'
  | 'awards'
  | 'certificates'
  | 'languages'
  | 'other'
  | 'custom'
export type SectionLayout = 'timeline' | 'list'
export type ResumeFontFamily = 'inter' | 'serif' | 'plex'
export type ThemeMode = 'light' | 'dark'
export type BuiltinResumeTemplateId = 'minimal' | 'modern' | 'compact'
export type ResumeBasicInfoLayout = 'centered' | 'profile' | 'sidebar'
export type ResumeAvatarPosition = 'right' | 'left' | 'center'
export type ResumeAvatarShape = 'rounded' | 'circle' | 'square'
export type ResumeSectionTemplateStyle =
  | 'ruled'
  | 'boxed'
  | 'accent'
  | 'plain'
  | 'band'
export type ResumeTemplateImageFit = 'contain' | 'cover'
export type ResumeTemplateId = string
export type WorkspaceView = 'resume' | 'templates' | 'trash' | 'models' | 'settings'
export type AgentResponseLanguage = 'follow' | 'zh' | 'en'
export type AgentBehaviorMode = 'balanced' | 'strict' | 'aggressive'

export interface CustomField {
  id: string
  label: string
  value: string
}

export interface ResumeBasicInfo {
  name: string
  headline: string
  phone: string
  email: string
  location: string
  avatar: string
  summary: string
  customFields: CustomField[]
}

export interface ResumeSectionItem {
  id: string
  title: string
  subtitle: string
  meta: string
  period: string
  description: string
  highlights: string[]
}

export interface ResumeSection {
  id: string
  kind: SectionKind
  layout: SectionLayout
  customTitle: string
  items: ResumeSectionItem[]
}

export interface ResumeData {
  basic: ResumeBasicInfo
  sections: ResumeSection[]
}

export type ResumeEditOperation =
  | {
      type: 'replace_field'
      path: string
      value: string | string[]
    }
  | {
      type: 'insert_section'
      section: ResumeSection
      index?: number
    }
  | {
      type: 'update_section'
      sectionId: string
      patch: Partial<ResumeSection>
    }
  | {
      type: 'delete_section'
      sectionId: string
    }
  | {
      type: 'reorder_sections'
      sectionIds: string[]
    }
  | {
      type: 'insert_item'
      sectionId: string
      item: ResumeSectionItem
      index?: number
    }
  | {
      type: 'update_item'
      sectionId: string
      itemId: string
      patch: Partial<ResumeSectionItem>
    }
  | {
      type: 'delete_item'
      sectionId: string
      itemId: string
    }
  | {
      type: 'reorder_items'
      sectionId: string
      itemIds: string[]
    }

export type ResumeDraftDiffKind = 'added' | 'modified' | 'deleted' | 'moved'

export interface ResumeDraftDiff {
  id: string
  operationId: string
  path: string
  kind: ResumeDraftDiffKind
  label: string
  sectionId?: string
  itemId?: string
  before?: unknown
  after?: unknown
}

export interface KeywordMatch {
  score: number
  matched: string[]
  missing: string[]
  summary: string
}

export interface ResumeTypographySettings {
  fontFamily: ResumeFontFamily
  fontSize: number
}

export interface ResumeTemplateSettings {
  pagePaddingTop: number
  pagePaddingX: number
  pagePaddingBottom: number
  sectionGap: number
  itemGap: number
  bodyLineHeight: number
  nameScale: number
  sectionTitleScale: number
  itemTitleScale: number
  metaScale: number
  bodyScale: number
  pageBackground: string
  surfaceColor: string
  headingColor: string
  bodyColor: string
  mutedColor: string
  dividerColor: string
  dividerThickness: number
}

export interface ResumeTemplateImageElement {
  id: string
  name: string
  src: string
  alt: string
  x: number
  y: number
  width: number
  height: number
  opacity: number
  borderWidth: number
  borderColor: string
  borderRadius: number
  objectFit: ResumeTemplateImageFit
  visible: boolean
}

export interface ResumeTemplateLayout {
  basicInfo: ResumeBasicInfoLayout
  section: ResumeSectionTemplateStyle
  avatarPosition: ResumeAvatarPosition
  avatarShape: ResumeAvatarShape
  avatarWidth: number
  avatarHeight: number
  avatarOffsetX: number
  avatarOffsetY: number
  avatarBorderWidth: number
  avatarBorderColor: string
  images: ResumeTemplateImageElement[]
}

export interface ResumeTemplateDefinition {
  id: ResumeTemplateId
  preset: BuiltinResumeTemplateId
  name: string
  description: string
  layout: ResumeTemplateLayout
  typography: ResumeTypographySettings
  settings: ResumeTemplateSettings
  updatedAt: string
  isBuiltIn?: boolean
}

export interface ModelConfig {
  id: string
  provider: string
  nickname: string
  apiKeyPreview: string
  model: string
  apiUrl: string
  temperature: number
  topP: number
  maxTokens: number | null
  systemPrompt: string
}

export interface LegacyModelConfig {
  provider?: string
  nickname?: string
  apiKey?: string
  apiKeyPreview?: string
  model?: string
  apiUrl?: string
  temperature?: number
  topP?: number
  topK?: number
  maxTokens?: number | null
  systemPrompt?: string
}

export interface AgentSettings {
  defaultModelId: string
  responseLanguage: AgentResponseLanguage
  behaviorMode: AgentBehaviorMode
  autoRunMatch: boolean
}

export interface ResumeWorkspaceItem {
  id: string
  title: string
  updatedAt: string
  resume: ResumeData
  jobBrief: string
  typography?: ResumeTypographySettings
  template?: ResumeTemplateId
  templateSettings?: ResumeTemplateSettings
}

export interface DeletedResumeWorkspaceItem extends ResumeWorkspaceItem {
  deletedAt: string
}

export interface DeletedResumeTemplateDefinition extends ResumeTemplateDefinition {
  deletedAt: string
}

export interface WorkspacePayload {
  resumes: ResumeWorkspaceItem[]
  defaultTemplateId?: ResumeTemplateId
  customTemplates?: ResumeTemplateDefinition[]
  deletedResumes?: DeletedResumeWorkspaceItem[]
  deletedTemplates?: DeletedResumeTemplateDefinition[]
  modelConfigs?: ModelConfig[]
  modelConfig?: LegacyModelConfig
  agentSettings?: AgentSettings
}

export interface WorkspaceSnapshot {
  resumes: ResumeWorkspaceItem[]
  defaultTemplateId?: ResumeTemplateId
  customTemplates?: ResumeTemplateDefinition[]
  deletedResumes?: DeletedResumeWorkspaceItem[]
  deletedTemplates?: DeletedResumeTemplateDefinition[]
  modelConfigs: ModelConfig[]
  modelConfig?: LegacyModelConfig
  agentSettings?: AgentSettings
  savedAt: string
}
