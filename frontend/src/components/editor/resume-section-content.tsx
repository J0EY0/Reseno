import { Plus } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { AppMessages } from "@/i18n";
import { createId } from "@/lib/resume-id";
import type { ResumeSectionMutation } from "@/lib/resume-section-mutations";
import type { ResumeSection } from "@/types/resume";

import { FormField } from "./form-field";
import { ResumeSectionItemsEditor } from "./resume-section-editors";
import { SortableEditorList } from "./sortable-editor-list";

export function ResumeSectionNameField({
  t,
  section,
  onMutation,
}: {
  t: AppMessages;
  section: ResumeSection;
  onMutation: (mutation: ResumeSectionMutation) => void;
}) {
  return (
    <FormField label={t.renameSection}>
      <Input
        autoFocus
        value={section.title}
        placeholder={t.placeholders.sectionName}
        onChange={(event) =>
          onMutation({
            type: "section.rename",
            sectionId: section.id,
            title: event.target.value,
          })
        }
      />
    </FormField>
  );
}

export function ResumeSectionContent({
  t,
  section,
  onMutation,
}: {
  t: AppMessages;
  section: ResumeSection;
  onMutation: (mutation: ResumeSectionMutation) => void;
}) {
  const [initiallyOpenItemId, setInitiallyOpenItemId] = useState<string | null>(
    null,
  );

  useEffect(() => {
    if (
      initiallyOpenItemId &&
      section.items.some((item) => item.id === initiallyOpenItemId)
    ) {
      // The id only seeds the new child's initial state; clearing it prevents
      // that entry from reopening whenever the whole section remounts.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setInitiallyOpenItemId(null);
    }
  }, [initiallyOpenItemId, section.items]);

  function addItem() {
    const itemId = createId("item");
    setInitiallyOpenItemId(itemId);
    onMutation({ type: "item.add", sectionId: section.id, itemId });
  }

  return (
    <div className="grid min-w-0 gap-2">
      <SortableEditorList
        items={section.items.map((item) => item.id)}
        onReorder={(itemId, overId) =>
          onMutation({
            type: "item.reorder",
            sectionId: section.id,
            sectionKind: section.kind,
            itemId,
            overId,
          })
        }
      >
        <ResumeSectionItemsEditor
          t={t}
          section={section}
          initiallyOpenItemId={initiallyOpenItemId}
          onMutation={onMutation}
        />
      </SortableEditorList>
      {section.kind !== "simple_list" ? (
        <Button
          type="button"
          variant="ghost"
          className="w-full text-muted-foreground"
          onClick={addItem}
        >
          <Plus aria-hidden="true" data-icon="inline-start" />
          {t.addItem[section.kind]}
        </Button>
      ) : null}
    </div>
  );
}
