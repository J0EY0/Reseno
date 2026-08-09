import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import type { ExperienceItem } from '@/types/resume'

import { FormField } from './form-field'
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
          <Input
            value={item.company}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.company}
            onChange={(event) => updateItem(item, { company: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.position}>
          <Input
            value={item.position}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.position}
            onChange={(event) => updateItem(item, { position: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.location}>
          <Input
            value={item.location}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.location}
            onChange={(event) => updateItem(item, { location: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.period}>
          <Input
            value={item.period}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.period}
            onChange={(event) => updateItem(item, { period: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.description} className="md:col-span-2">
          <Textarea
            rows={2}
            value={item.description}
            className={`${compactResumeFieldClassName} min-h-16 resize-y`}
            placeholder={t.placeholders.description}
            onChange={(event) => updateItem(item, { description: event.target.value })}
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
