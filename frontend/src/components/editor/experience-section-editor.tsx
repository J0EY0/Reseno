import type { ExperienceItem } from '@/types/resume'

import { FormField } from './form-field'
import { InlineTextInput } from './inline-text-input'
import { ResumeItemEditorShell } from './resume-item-editor-shell'
import {
  HighlightsField,
  compactResumeFieldClassName,
} from './resume-section-editor-fields'
import type { TypedSectionEditorProps } from './resume-section-editor-types'

export function ExperienceSectionEditor({
  t,
  section,
  initiallyOpenItemId,
  onUpdateItem,
  onRemoveItem,
  onMoveItem,
}: TypedSectionEditorProps<'experience'>) {
  function updateItem(
    item: ExperienceItem,
    patch: Partial<Omit<ExperienceItem, 'id'>>,
  ) {
    onUpdateItem({
      type: 'item.update',
      sectionId: section.id,
      sectionKind: 'experience',
      itemId: item.id,
      patch,
    })
  }

  return section.items.map((item, index) => (
    <ResumeItemEditorShell
      key={item.id}
      index={index}
      itemLabel={t.itemCountSingular}
      initiallyOpen={item.id === initiallyOpenItemId}
      canMoveUp={index > 0}
      canMoveDown={index < section.items.length - 1}
      removeLabel={t.removeItem}
      moveUpLabel={t.moveItemUp}
      moveDownLabel={t.moveItemDown}
      toggleLabel={t.toggleItem}
      onRemove={() => onRemoveItem(item.id)}
      onMoveUp={() => onMoveItem(item.id, 'up')}
      onMoveDown={() => onMoveItem(item.id, 'down')}
    >
      <div className="grid min-w-0 gap-3 md:grid-cols-2">
        <FormField label={t.fieldLabels.company}>
          <InlineTextInput
            t={t}
            aria-label={t.fieldLabels.company}
            value={item.company}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.company}
            onChange={(value) => updateItem(item, { company: value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.position}>
          <InlineTextInput
            t={t}
            aria-label={t.fieldLabels.position}
            value={item.position}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.position}
            onChange={(value) => updateItem(item, { position: value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.location}>
          <InlineTextInput
            t={t}
            aria-label={t.fieldLabels.location}
            value={item.location}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.location}
            onChange={(value) => updateItem(item, { location: value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.period}>
          <InlineTextInput
            t={t}
            aria-label={t.fieldLabels.period}
            value={item.period}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.period}
            onChange={(value) => updateItem(item, { period: value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.description} className="md:col-span-2">
          <InlineTextInput
            t={t}
            aria-label={t.fieldLabels.description}
            multiline
            value={item.description}
            className={`${compactResumeFieldClassName} min-h-16`}
            placeholder={t.placeholders.description}
            onChange={(value) => updateItem(item, { description: value })}
          />
        </FormField>
        <HighlightsField
          t={t}
          value={item.highlights}
          onChange={(highlights) => updateItem(item, { highlights })}
        />
      </div>
    </ResumeItemEditorShell>
  ))
}
