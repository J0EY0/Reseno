import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import type { AchievementItem } from '@/types/resume'

import { FormField } from './form-field'
import { ResumeItemEditorShell } from './resume-item-editor-shell'
import { compactResumeFieldClassName } from './resume-section-editor-fields'
import type { TypedSectionEditorProps } from './resume-section-editor-types'

export function AchievementSectionEditor({
  t,
  section,
  initiallyOpenItemId,
  onUpdateItem,
  onRemoveItem,
  onMoveItem,
}: TypedSectionEditorProps<'achievement'>) {
  function updateItem(
    item: AchievementItem,
    patch: Partial<Omit<AchievementItem, 'id'>>,
  ) {
    onUpdateItem({
      type: 'item.update',
      sectionId: section.id,
      sectionKind: 'achievement',
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
        <FormField label={t.fieldLabels.achievementName}>
          <Input
            value={item.name}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.achievementName}
            onChange={(event) => updateItem(item, { name: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.issuer}>
          <Input
            value={item.issuer}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.issuer}
            onChange={(event) => updateItem(item, { issuer: event.target.value })}
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
        <FormField label={t.fieldLabels.url}>
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
            placeholder={t.placeholders.description}
            onChange={(event) => updateItem(item, { description: event.target.value })}
          />
        </FormField>
      </div>
    </ResumeItemEditorShell>
  ))
}
