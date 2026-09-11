import { Input } from "@/components/ui/input";
import type { ProjectItem } from "@/types/resume";

import { FormField } from "./form-field";
import { InlineTextInput } from "./inline-text-input";
import { InlineTextListInput } from "./inline-text-list-input";
import { ResumeItemEditorShell } from "./resume-item-editor-shell";
import {
  HighlightsField,
  compactResumeFieldClassName,
} from "./resume-section-editor-fields";
import type { TypedSectionEditorProps } from "./resume-section-editor-types";

export function ProjectSectionEditor({
  t,
  section,
  initiallyOpenItemId,
  onUpdateItem,
  onRemoveItem,
  onMoveItem,
}: TypedSectionEditorProps<"project">) {
  function updateItem(
    item: ProjectItem,
    patch: Partial<Omit<ProjectItem, "id">>,
  ) {
    onUpdateItem({
      type: "item.update",
      sectionId: section.id,
      sectionKind: "project",
      itemId: item.id,
      patch,
    });
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
      onMoveUp={() => onMoveItem(item.id, "up")}
      onMoveDown={() => onMoveItem(item.id, "down")}
    >
      <div className="grid min-w-0 gap-3 md:grid-cols-2">
        <FormField label={t.fieldLabels.projectName}>
          <InlineTextInput
            autoFocus={item.id === initiallyOpenItemId}
            t={t}
            aria-label={t.fieldLabels.projectName}
            value={item.name}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.projectName}
            onChange={(value) => updateItem(item, { name: value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.role}>
          <InlineTextInput
            t={t}
            aria-label={t.fieldLabels.role}
            value={item.role}
            className={compactResumeFieldClassName}
            placeholder={t.placeholders.role}
            onChange={(value) => updateItem(item, { role: value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.techStack}>
          <InlineTextListInput
            t={t}
            aria-label={t.fieldLabels.techStack}
            className={compactResumeFieldClassName}
            value={item.techStack}
            placeholder={t.placeholders.techStack}
            onChange={(techStack) => updateItem(item, { techStack })}
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
  ));
}
