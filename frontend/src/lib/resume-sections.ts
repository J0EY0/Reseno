import { stripRichText } from '@/lib/rich-text'
import type {
  AchievementItem,
  EducationItem,
  ExperienceItem,
  ProjectItem,
  ResumeData,
  ResumeSection,
  SectionItemByKind,
  SectionKind,
  SectionLayout,
  SimpleListItem,
} from '@/types/resume'

import { createId } from './resume-id'

export interface RenderableSectionItem {
  id: string
  title: string
  subtitle: string
  meta: string
  period: string
  description: string
  highlights: string[]
  content: string
  url: string
}

export interface RenderableResumeSection {
  id: string
  kind: SectionKind
  title: string
  layout: SectionLayout
  items: RenderableSectionItem[]
}

export const SECTION_RENDER_FAMILY: Record<SectionKind, SectionLayout> = {
  education: 'timeline',
  experience: 'timeline',
  project: 'timeline',
  achievement: 'timeline',
  simple_list: 'list',
}

export const SECTION_ITEM_FIELDS = {
  education: [
    'school',
    'degree',
    'major',
    'gpa',
    'location',
    'period',
    'description',
    'highlights',
  ],
  experience: [
    'company',
    'position',
    'location',
    'period',
    'description',
    'highlights',
  ],
  project: [
    'name',
    'role',
    'techStack',
    'period',
    'url',
    'description',
    'highlights',
  ],
  achievement: ['name', 'issuer', 'date', 'url', 'description'],
  simple_list: ['content'],
} as const satisfies Record<SectionKind, readonly string[]>

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]) {
  const keys = Object.keys(value)
  return keys.length === expected.length && keys.every((key) => expected.includes(key))
}

function hasStringFields(value: Record<string, unknown>, fields: readonly string[]) {
  return fields.every((field) => typeof value[field] === 'string')
}

export function isSectionItemForKind<K extends SectionKind>(
  kind: K,
  value: unknown,
): value is SectionItemByKind[K] {
  if (!isRecord(value) || typeof value.id !== 'string' || !value.id) {
    return false
  }

  const expectedKeys = ['id', ...SECTION_ITEM_FIELDS[kind]]
  if (!hasExactKeys(value, expectedKeys)) {
    return false
  }

  switch (kind) {
    case 'education':
      return (
        hasStringFields(value, [
          'school',
          'degree',
          'major',
          'gpa',
          'location',
          'period',
          'description',
        ]) &&
        Array.isArray(value.highlights) &&
        value.highlights.every((entry) => typeof entry === 'string')
      )
    case 'experience':
      return (
        hasStringFields(value, [
          'company',
          'position',
          'location',
          'period',
          'description',
        ]) &&
        Array.isArray(value.highlights) &&
        value.highlights.every((entry) => typeof entry === 'string')
      )
    case 'project':
      return (
        hasStringFields(value, [
          'name',
          'role',
          'period',
          'url',
          'description',
        ]) &&
        Array.isArray(value.techStack) &&
        value.techStack.every((entry) => typeof entry === 'string') &&
        Array.isArray(value.highlights) &&
        value.highlights.every((entry) => typeof entry === 'string')
      )
    case 'achievement':
      return hasStringFields(value, [
        'name',
        'issuer',
        'date',
        'url',
        'description',
      ])
    case 'simple_list':
      return typeof value.content === 'string'
  }
}

export function isCanonicalResumeSection(value: unknown): value is ResumeSection {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['id', 'kind', 'title', 'items']) ||
    typeof value.id !== 'string' ||
    !value.id ||
    typeof value.title !== 'string' ||
    typeof value.kind !== 'string' ||
    !Object.hasOwn(SECTION_ITEM_FIELDS, value.kind) ||
    !Array.isArray(value.items)
  ) {
    return false
  }

  const kind = value.kind as SectionKind
  if (kind === 'simple_list' && value.items.length !== 1) {
    return false
  }
  return value.items.every((item) => isSectionItemForKind(kind, item))
}

export function isCanonicalResumeData(value: unknown): value is ResumeData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['schemaVersion', 'basic', 'sections']) ||
    value.schemaVersion !== 2 ||
    !isRecord(value.basic) ||
    !hasExactKeys(value.basic, [
      'name',
      'headline',
      'phone',
      'email',
      'location',
      'avatar',
      'summary',
      'customFields',
    ]) ||
    !hasStringFields(value.basic, [
      'name',
      'headline',
      'phone',
      'email',
      'location',
      'avatar',
      'summary',
    ]) ||
    !Array.isArray(value.basic.customFields) ||
    !value.basic.customFields.every(
      (field) =>
        isRecord(field) &&
        hasExactKeys(field, ['id', 'type', 'label', 'value']) &&
        typeof field.id === 'string' &&
        field.id.length > 0 &&
        ['email', 'phone', 'url', 'text'].includes(String(field.type)) &&
        typeof field.label === 'string' &&
        typeof field.value === 'string',
    ) ||
    !Array.isArray(value.sections) ||
    !value.sections.every(isCanonicalResumeSection)
  ) {
    return false
  }

  // Match the backend's document-wide identity invariant so an imported JSON
  // file cannot enter the editor only to fail later during autosave.
  const sectionIds = new Set<string>()
  const itemIds = new Set<string>()
  for (const section of value.sections) {
    if (sectionIds.has(section.id)) {
      return false
    }
    sectionIds.add(section.id)
    for (const item of section.items) {
      if (itemIds.has(item.id)) {
        return false
      }
      itemIds.add(item.id)
    }
  }

  return true
}

function createEducationItem(): EducationItem {
  return {
    id: createId('item'),
    school: '',
    degree: '',
    major: '',
    gpa: '',
    location: '',
    period: '',
    description: '',
    highlights: [],
  }
}

function createExperienceItem(): ExperienceItem {
  return {
    id: createId('item'),
    company: '',
    position: '',
    location: '',
    period: '',
    description: '',
    highlights: [],
  }
}

function createProjectItem(): ProjectItem {
  return {
    id: createId('item'),
    name: '',
    role: '',
    techStack: [],
    period: '',
    url: '',
    description: '',
    highlights: [],
  }
}

function createAchievementItem(): AchievementItem {
  return {
    id: createId('item'),
    name: '',
    issuer: '',
    date: '',
    url: '',
    description: '',
  }
}

function createSimpleListItem(): SimpleListItem {
  return {
    id: createId('item'),
    content: '',
  }
}

export function createSectionItem<K extends SectionKind>(
  kind: K,
): SectionItemByKind[K] {
  // The cast stays inside this module so callers retain a correlated kind/item type.
  switch (kind) {
    case 'education':
      return createEducationItem() as SectionItemByKind[K]
    case 'experience':
      return createExperienceItem() as SectionItemByKind[K]
    case 'project':
      return createProjectItem() as SectionItemByKind[K]
    case 'achievement':
      return createAchievementItem() as SectionItemByKind[K]
    case 'simple_list':
      return createSimpleListItem() as SectionItemByKind[K]
  }
}

export function createResumeSection(kind: SectionKind): ResumeSection {
  const id = createId('section')

  switch (kind) {
    case 'education':
      return { id, kind, title: '', items: [createEducationItem()] }
    case 'experience':
      return { id, kind, title: '', items: [createExperienceItem()] }
    case 'project':
      return { id, kind, title: '', items: [createProjectItem()] }
    case 'achievement':
      return { id, kind, title: '', items: [createAchievementItem()] }
    case 'simple_list':
      return { id, kind, title: '', items: [createSimpleListItem()] }
  }
}

function hasText(values: string[]) {
  return values.some((value) => stripRichText(value).trim())
}

export function parseCommaSeparatedItems(value: string) {
  return value
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

export function hasSectionItemContent(
  kind: 'education',
  item: EducationItem,
): boolean
export function hasSectionItemContent(
  kind: 'experience',
  item: ExperienceItem,
): boolean
export function hasSectionItemContent(kind: 'project', item: ProjectItem): boolean
export function hasSectionItemContent(
  kind: 'achievement',
  item: AchievementItem,
): boolean
export function hasSectionItemContent(
  kind: 'simple_list',
  item: SimpleListItem,
): boolean
export function hasSectionItemContent(
  kind: SectionKind,
  item: SectionItemByKind[SectionKind],
) {
  switch (kind) {
    case 'education': {
      const value = item as EducationItem
      return hasText([
        value.school,
        value.degree,
        value.major,
        value.gpa,
        value.location,
        value.period,
        value.description,
        ...value.highlights,
      ])
    }
    case 'experience': {
      const value = item as ExperienceItem
      return hasText([
        value.company,
        value.position,
        value.location,
        value.period,
        value.description,
        ...value.highlights,
      ])
    }
    case 'project': {
      const value = item as ProjectItem
      return hasText([
        value.name,
        value.role,
        ...value.techStack,
        value.period,
        value.url,
        value.description,
        ...value.highlights,
      ])
    }
    case 'achievement': {
      const value = item as AchievementItem
      return hasText([
        value.name,
        value.issuer,
        value.date,
        value.url,
        value.description,
      ])
    }
    case 'simple_list':
      return hasText([(item as SimpleListItem).content])
  }
}

export function hasSectionContent(section: ResumeSection) {
  switch (section.kind) {
    case 'education':
      return section.items.some((item) => hasSectionItemContent('education', item))
    case 'experience':
      return section.items.some((item) => hasSectionItemContent('experience', item))
    case 'project':
      return section.items.some((item) => hasSectionItemContent('project', item))
    case 'achievement':
      return section.items.some((item) => hasSectionItemContent('achievement', item))
    case 'simple_list':
      return section.items.some((item) => hasSectionItemContent('simple_list', item))
  }
}

function createRenderableItem(
  item: Omit<RenderableSectionItem, 'content' | 'url'> &
    Partial<Pick<RenderableSectionItem, 'content' | 'url'>>,
): RenderableSectionItem {
  return {
    content: '',
    url: '',
    ...item,
  }
}

export function projectResumeSection(
  section: ResumeSection,
): RenderableResumeSection {
  switch (section.kind) {
    case 'education':
      return {
        ...section,
        layout: SECTION_RENDER_FAMILY.education,
        items: section.items.map((item) =>
          createRenderableItem({
            id: item.id,
            title: item.school,
            subtitle: [item.degree, item.major].filter(Boolean).join(' · '),
            meta: [item.gpa, item.location].filter(Boolean).join(' · '),
            period: item.period,
            description: item.description,
            highlights: item.highlights,
          }),
        ),
      }
    case 'experience':
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
      }
    case 'project':
      return {
        ...section,
        layout: SECTION_RENDER_FAMILY.project,
        items: section.items.map((item) =>
          createRenderableItem({
            id: item.id,
            title: item.name,
            subtitle: item.role,
            meta: item.techStack.join(' · '),
            period: item.period,
            description: item.description,
            highlights: item.highlights,
            url: item.url,
          }),
        ),
      }
    case 'achievement':
      return {
        ...section,
        layout: SECTION_RENDER_FAMILY.achievement,
        items: section.items.map((item) =>
          createRenderableItem({
            id: item.id,
            title: item.name,
            subtitle: item.issuer,
            meta: '',
            period: item.date,
            description: item.description,
            highlights: [],
            url: item.url,
          }),
        ),
      }
    case 'simple_list':
      return {
        ...section,
        layout: SECTION_RENDER_FAMILY.simple_list,
        items: [
          createRenderableItem({
            id: section.items[0].id,
            title: '',
            subtitle: '',
            meta: '',
            period: '',
            description: '',
            highlights: [],
            content: section.items[0].content,
          }),
        ],
      }
  }
}

export function projectResumeSections(sections: ResumeSection[]) {
  return sections.map(projectResumeSection)
}

type UpdateItemMutation = {
  [K in SectionKind]: {
    type: 'item.update'
    sectionId: string
    sectionKind: K
    itemId: string
    patch: Partial<Omit<SectionItemByKind[K], 'id'>>
  }
}[SectionKind]

type RestoreItemMutation = {
  [K in SectionKind]: {
    type: 'item.restore'
    sectionId: string
    sectionKind: K
    item: SectionItemByKind[K]
    index: number
  }
}[SectionKind]

export type ResumeSectionMutation =
  | { type: 'section.rename'; sectionId: string; title: string }
  | { type: 'item.add'; sectionId: string; itemId?: string }
  | { type: 'item.remove'; sectionId: string; itemId: string }
  | {
      type: 'item.move'
      sectionId: string
      itemId: string
      direction: 'up' | 'down'
    }
  | RestoreItemMutation
  | UpdateItemMutation

export type ResumeSectionMutationResult =
  | { status: 'applied'; sections: ResumeSection[] }
  | { status: 'unchanged'; sections: ResumeSection[] }
  | {
      status: 'rejected'
      sections: ResumeSection[]
      code:
        | 'SECTION_NOT_FOUND'
        | 'SECTION_KIND_MISMATCH'
        | 'ITEM_NOT_FOUND'
        | 'ITEM_ID_CONFLICT'
        | 'INVALID_ITEM'
        | 'SIMPLE_LIST_CARDINALITY'
    }

function replaceSection(
  sections: ResumeSection[],
  sectionId: string,
  replacement: ResumeSection,
) {
  return sections.map((section) =>
    section.id === sectionId ? replacement : section,
  )
}

function containsItemId(sections: ResumeSection[], itemId: string) {
  return sections.some((section) =>
    section.items.some((item) => item.id === itemId),
  )
}

export function applySectionMutation(
  sections: ResumeSection[],
  mutation: ResumeSectionMutation,
): ResumeSectionMutationResult {
  const section = sections.find((candidate) => candidate.id === mutation.sectionId)
  if (!section) {
    return { status: 'rejected', sections, code: 'SECTION_NOT_FOUND' }
  }

  if (mutation.type === 'section.rename') {
    if (section.title === mutation.title) {
      return { status: 'unchanged', sections }
    }
    return {
      status: 'applied',
      sections: replaceSection(sections, section.id, {
        ...section,
        title: mutation.title,
      }),
    }
  }

  if (mutation.type === 'item.add') {
    if (section.kind === 'simple_list') {
      return { status: 'rejected', sections, code: 'SIMPLE_LIST_CARDINALITY' }
    }
    if (mutation.itemId && containsItemId(sections, mutation.itemId)) {
      return { status: 'rejected', sections, code: 'ITEM_ID_CONFLICT' }
    }
    const nextItem = createSectionItem(section.kind)
    if (mutation.itemId) {
      // The editor pre-generates an id so it can open and focus precisely the
      // item created by this interaction. Import/Agent callers may omit it.
      nextItem.id = mutation.itemId
    }
    // A single cast is required because TypeScript cannot preserve a correlated
    // union while spreading an item into an unknown member of that union.
    const replacement = {
      ...section,
      items: [...section.items, nextItem],
    } as ResumeSection
    return {
      status: 'applied',
      sections: replaceSection(sections, section.id, replacement),
    }
  }

  if (mutation.type === 'item.remove') {
    if (section.kind === 'simple_list') {
      return { status: 'rejected', sections, code: 'SIMPLE_LIST_CARDINALITY' }
    }
    if (!section.items.some((item) => item.id === mutation.itemId)) {
      return { status: 'rejected', sections, code: 'ITEM_NOT_FOUND' }
    }
    const replacement = {
      ...section,
      items: section.items.filter((item) => item.id !== mutation.itemId),
    } as ResumeSection
    return {
      status: 'applied',
      sections: replaceSection(sections, section.id, replacement),
    }
  }

  if (mutation.type === 'item.restore') {
    if (section.kind === 'simple_list') {
      return { status: 'rejected', sections, code: 'SIMPLE_LIST_CARDINALITY' }
    }
    if (section.kind !== mutation.sectionKind) {
      return { status: 'rejected', sections, code: 'SECTION_KIND_MISMATCH' }
    }
    if (!isSectionItemForKind(mutation.sectionKind, mutation.item)) {
      return { status: 'rejected', sections, code: 'INVALID_ITEM' }
    }
    if (containsItemId(sections, mutation.item.id)) {
      return { status: 'rejected', sections, code: 'ITEM_ID_CONFLICT' }
    }

    // Undo may run after an autosave and after other edits reordered the list.
    // Clamp the captured position against the current section instead of
    // rejecting a still-valid restore.
    const requestedIndex = Number.isFinite(mutation.index)
      ? Math.trunc(mutation.index)
      : section.items.length
    const restoreIndex = Math.min(
      Math.max(requestedIndex, 0),
      section.items.length,
    )
    const nextItems = [...section.items]
    nextItems.splice(restoreIndex, 0, mutation.item)
    const replacement = { ...section, items: nextItems } as ResumeSection
    return {
      status: 'applied',
      sections: replaceSection(sections, section.id, replacement),
    }
  }

  if (mutation.type === 'item.move') {
    if (section.kind === 'simple_list') {
      return { status: 'rejected', sections, code: 'SIMPLE_LIST_CARDINALITY' }
    }
    const currentIndex = section.items.findIndex(
      (item) => item.id === mutation.itemId,
    )
    if (currentIndex < 0) {
      return { status: 'rejected', sections, code: 'ITEM_NOT_FOUND' }
    }
    const targetIndex =
      mutation.direction === 'up' ? currentIndex - 1 : currentIndex + 1
    if (targetIndex < 0 || targetIndex >= section.items.length) {
      return { status: 'unchanged', sections }
    }

    const nextItems = [...section.items]
    const [movedItem] = nextItems.splice(currentIndex, 1)
    nextItems.splice(targetIndex, 0, movedItem)
    const replacement = { ...section, items: nextItems } as ResumeSection
    return {
      status: 'applied',
      sections: replaceSection(sections, section.id, replacement),
    }
  }

  if (section.kind !== mutation.sectionKind) {
    return { status: 'rejected', sections, code: 'SECTION_KIND_MISMATCH' }
  }
  if (!section.items.some((item) => item.id === mutation.itemId)) {
    return { status: 'rejected', sections, code: 'ITEM_NOT_FOUND' }
  }

  const replacement = {
    ...section,
    items: section.items.map((item) =>
      item.id === mutation.itemId ? { ...item, ...mutation.patch } : item,
    ),
  } as ResumeSection
  return {
    status: 'applied',
    sections: replaceSection(sections, section.id, replacement),
  }
}
