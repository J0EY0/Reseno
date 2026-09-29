import type { SimpleListItem } from "@/types/resume";

import { SimpleContentField } from "./resume-section-editor-fields";
import type { TypedSectionEditorProps } from "./resume-section-editor-types";

export function SimpleListSectionEditor({
  t,
  section,
  onUpdateItem,
}: Omit<
  TypedSectionEditorProps<"simple_list">,
  "onRemoveItem" | "onMoveItem" | "expandedItemIds" | "onItemOpenChange"
>) {
  const item = section.items[0];

  function updateItem(
    item: SimpleListItem,
    patch: Partial<Omit<SimpleListItem, "id">>,
  ) {
    onUpdateItem({
      type: "item.update",
      sectionId: section.id,
      sectionKind: "simple_list",
      itemId: item.id,
      patch,
    });
  }

  return (
    <div className="min-w-0" data-resume-item-id={item.id}>
      <SimpleContentField
        t={t}
        value={item.content}
        onChange={(content) => updateItem(item, { content })}
      />
    </div>
  );
}
