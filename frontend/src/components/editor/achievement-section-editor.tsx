import { Input } from "@/components/ui/input";
import { FieldGroup } from "@/components/ui/field";
import { getRichTextPlainText } from "@/lib/rich-text";
import type { AchievementItem } from "@/types/resume";

import { FormField } from "./form-field";
import { InlineTextInput } from "./inline-text-input";
import { ResumeItemEditorShell } from "./resume-item-editor-shell";
import { compactResumeFieldClassName } from "./resume-section-editor-fields";
import type { TypedSectionEditorProps } from "./resume-section-editor-types";

export function AchievementSectionEditor({
  t,
  section,
  initiallyOpenItemId,
  onUpdateItem,
  onRemoveItem,
  onMoveItem,
}: TypedSectionEditorProps<"achievement">) {
  function updateItem(
    item: AchievementItem,
    patch: Partial<Omit<AchievementItem, "id">>,
  ) {
    onUpdateItem({
      type: "item.update",
      sectionId: section.id,
      sectionKind: "achievement",
      itemId: item.id,
      patch,
    });
  }

  return section.items.map((item, index) => (
    <ResumeItemEditorShell
      key={item.id}
      itemId={item.id}
      index={index}
      itemLabel={t.itemLabel}
      title={item.name}
      titleEditor={
        <InlineTextInput
          autoFocus={item.id === initiallyOpenItemId}
          t={t}
          aria-label={t.fieldLabels.achievementName}
          value={item.name}
          className={`${compactResumeFieldClassName} editor-item-title`}
          placeholder={t.placeholders.achievementName}
          onChange={(value) => updateItem(item, { name: value })}
        />
      }
      summary={[item.issuer, item.date]
        .map((value) => getRichTextPlainText(value).trim())
        .filter(Boolean)
        .join(" · ")}
      initiallyOpen={item.id === initiallyOpenItemId}
      canMoveUp={index > 0}
      canMoveDown={index < section.items.length - 1}
      removeLabel={t.removeItem}
      moveUpLabel={t.moveItemUp}
      moveDownLabel={t.moveItemDown}
      toggleLabel={t.toggleItem}
      onRemove={() => onRemoveItem(item.id)}
      onMoveUp={() => onMoveItem(item.id, "up")}
      onMoveDown={() => onMoveItem(item.id, "down")}
    >
      <FieldGroup className="min-w-0 gap-4">
        <FieldGroup className="grid min-w-0 gap-4 @min-[20rem]/field-group:grid-cols-2">
          <FormField label={t.fieldLabels.issuer}>
            <InlineTextInput
              t={t}
              aria-label={t.fieldLabels.issuer}
              value={item.issuer}
              className={compactResumeFieldClassName}
              placeholder={t.placeholders.issuer}
              onChange={(value) => updateItem(item, { issuer: value })}
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
        </FieldGroup>
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
        <FormField label={t.fieldLabels.description}>
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
      </FieldGroup>
    </ResumeItemEditorShell>
  ));
}
