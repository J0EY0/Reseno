import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import type { PublicationItem } from '@/types/resume'

import { FormField } from './form-field'
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
          <Textarea
            rows={2}
            value={item.title}
            className={`${compactResumeFieldClassName} min-h-16 resize-y`}
            placeholder={t.placeholders.publicationTitle}
            onChange={(event) => updateItem(item, { title: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.authors} className="md:col-span-2">
          <Textarea
            rows={2}
            value={item.authors}
            className={`${compactResumeFieldClassName} min-h-16 resize-y`}
            placeholder={t.placeholders.authors}
            onChange={(event) => updateItem(item, { authors: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.venue}>
          <Input
            value={item.venue}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.venue}
            onChange={(event) => updateItem(item, { venue: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.date}>
          <Input
            value={item.date}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.date}
            onChange={(event) => updateItem(item, { date: event.target.value })}
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
          <Textarea
            rows={2}
            value={item.description}
            className={`${compactResumeFieldClassName} min-h-16 resize-y`}
            placeholder={t.placeholders.publicationDescription}
            onChange={(event) =>
              updateItem(item, { description: event.target.value })
            }
          />
        </FormField>
      </div>
    </ResumeItemEditorShell>
  ))
}
