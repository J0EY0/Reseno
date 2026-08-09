import {
  createSectionItem,
  isSectionItemForKind,
} from '@/lib/resume-sections'
import type {
  ResumeSection,
  SectionItemByKind,
  SectionKind,
} from '@/types/resume'

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

