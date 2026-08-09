import type { SimpleListItem } from '@/types/resume'

import { SimpleContentField } from './resume-section-editor-fields'
import type { TypedSectionEditorProps } from './resume-section-editor-types'

export function SimpleListSectionEditor({
  t,
  section,
  onUpdateItem,
}: Omit<TypedSectionEditorProps<'simple_list'>, 'onRemoveItem' | 'onMoveItem'>) {
  const item = section.items[0]

  function updateItem(
    item: SimpleListItem,
    patch: Partial<Omit<SimpleListItem, 'id'>>,
  ) {
    onUpdateItem({
      type: 'item.update',
      sectionId: section.id,
      sectionKind: 'simple_list',
      itemId: item.id,
      patch,
    })
  }

  return (
    <SimpleContentField
      t={t}
      value={item.content}
      onChange={(content) => updateItem(item, { content })}
    />
  )
}
