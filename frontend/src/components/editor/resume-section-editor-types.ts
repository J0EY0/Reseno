import type { AppMessages } from '@/i18n'
import type { ResumeSectionMutation } from '@/lib/resume-section-mutations'
import type { ResumeSection, ResumeSectionOf } from '@/types/resume'

export type ItemUpdateMutation = Extract<
  ResumeSectionMutation,
  { type: 'item.update' }
>

export type TypedSectionEditorProps<K extends ResumeSection['kind']> = {
  t: AppMessages
  section: ResumeSectionOf<K>
  initiallyOpenItemId?: string | null
  onUpdateItem: (mutation: ItemUpdateMutation) => void
  onRemoveItem: (itemId: string) => void
  onMoveItem: (itemId: string, direction: 'up' | 'down') => void
}
