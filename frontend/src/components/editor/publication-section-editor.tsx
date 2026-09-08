import { Input } from '@/components/ui/input'
import type { PublicationItem } from '@/types/resume'

import { FormField } from './form-field'
import { InlineTextInput } from './inline-text-input'
import { ResumeItemEditorShell } from './resume-item-editor-shell'
import { compactResumeFieldClassName } from './resume-section-editor-fields'
import type { TypedSectionEditorProps } from './resume-section-editor-types'

export function PublicationSectionEditor({
  t,
  section,
  initiallyOpenItemId,
  onUpdateItem,
  onRemoveItem,
  onMoveItem,
}: TypedSectionEditorProps<'publication'>) {
  function updateItem(
    item: PublicationItem,
    patch: Partial<Omit<PublicationItem, 'id'>>,
  ) {
    onUpdateItem({
      type: 'item.update',
      sectionId: section.id,
      sectionKind: 'publication',
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
        <FormField label={t.fieldLabels.publicationTitle} className="md:col-span-2">
          <InlineTextInput
            t={t}
            aria-label={t.fieldLabels.publicationTitle}
            multiline
            value={item.title}
            className={`${compactResumeFieldClassName} min-h-16`}
            placeholder={t.placeholders.publicationTitle}
            onChange={(value) => updateItem(item, { title: value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.authors} className="md:col-span-2">
          <InlineTextInput
            t={t}
            aria-label={t.fieldLabels.authors}
            multiline
            value={item.authors}
            className={`${compactResumeFieldClassName} min-h-16`}
            placeholder={t.placeholders.authors}
            onChange={(value) => updateItem(item, { authors: value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.venue}>
          <InlineTextInput
            t={t}
            aria-label={t.fieldLabels.venue}
            value={item.venue}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.venue}
            onChange={(value) => updateItem(item, { venue: value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.date}>
          <InlineTextInput
            t={t}
            aria-label={t.fieldLabels.date}
            value={item.date}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.date}
            onChange={(value) => updateItem(item, { date: value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.url} className="md:col-span-2">
          <Input
            type="url"
            inputMode="url"
            value={item.url}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.url}
            onChange={(event) => updateItem(item, { url: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.description} className="md:col-span-2">
          <InlineTextInput
            t={t}
            aria-label={t.fieldLabels.description}
            multiline
            value={item.description}
            className={`${compactResumeFieldClassName} min-h-16`}
            placeholder={t.placeholders.publicationDescription}
            onChange={(value) => updateItem(item, { description: value })}
          />
        </FormField>
      </div>
    </ResumeItemEditorShell>
  ))
}
