import type { EducationItem } from '@/types/resume'

import { FormField } from './form-field'
import { InlineTextInput } from './inline-text-input'
import { ResumeItemEditorShell } from './resume-item-editor-shell'
import {
  HighlightsField,
  compactResumeFieldClassName,
} from './resume-section-editor-fields'
import type { TypedSectionEditorProps } from './resume-section-editor-types'

export function EducationSectionEditor({
  t,
  section,
  initiallyOpenItemId,
  onUpdateItem,
  onRemoveItem,
  onMoveItem,
}: TypedSectionEditorProps<'education'>) {
  function updateItem(
    item: EducationItem,
    patch: Partial<Omit<EducationItem, 'id'>>,
  ) {
    onUpdateItem({
      type: 'item.update',
      sectionId: section.id,
      sectionKind: 'education',
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
        <FormField label={t.fieldLabels.school}>
          <InlineTextInput
            t={t}
            aria-label={t.fieldLabels.school}
            value={item.school}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.school}
            onChange={(value) => updateItem(item, { school: value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.degree}>
          <InlineTextInput
            t={t}
            aria-label={t.fieldLabels.degree}
            value={item.degree}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.degree}
            onChange={(value) => updateItem(item, { degree: value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.major}>
          <InlineTextInput
            t={t}
            aria-label={t.fieldLabels.major}
            value={item.major}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.major}
            onChange={(value) => updateItem(item, { major: value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.gpa}>
          <InlineTextInput
            t={t}
            aria-label={t.fieldLabels.gpa}
            value={item.gpa}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.gpa}
            onChange={(value) => updateItem(item, { gpa: value })}
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
