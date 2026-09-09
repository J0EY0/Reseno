import { toast } from "sonner";

import type { AppMessages } from "@/i18n";
import type { ResumeSectionMutation } from "@/lib/resume-section-mutations";
import type { ResumeSection } from "@/types/resume";

import { AchievementSectionEditor } from "./achievement-section-editor";
import { EducationSectionEditor } from "./education-section-editor";
import { ExperienceSectionEditor } from "./experience-section-editor";
import { ProjectSectionEditor } from "./project-section-editor";
import { PublicationSectionEditor } from "./publication-section-editor";
import type { ItemUpdateMutation } from "./resume-section-editor-types";
import { SimpleListSectionEditor } from "./simple-list-section-editor";

type SectionItemsEditorProps = {
  t: AppMessages;
  section: ResumeSection;
  initiallyOpenItemId?: string | null;
  onMutation: (mutation: ResumeSectionMutation) => void;
};

export function ResumeSectionItemsEditor({
  t,
  section,
  initiallyOpenItemId,
  onMutation,
}: SectionItemsEditorProps) {
  const onRemoveItem = (itemId: string) => {
    const itemIndex = section.items.findIndex((item) => item.id === itemId);
    if (itemIndex < 0 || section.kind === "simple_list") {
      return;
    }

    // Keep the discriminated item type paired with its section kind. A generic
    // object here would widen `item` and weaken the restore mutation contract.
    let restoreMutation: ResumeSectionMutation;
    switch (section.kind) {
      case "education":
        restoreMutation = {
          type: "item.restore",
          sectionId: section.id,
          sectionKind: section.kind,
          item: section.items[itemIndex],
          index: itemIndex,
        };
        break;
      case "experience":
        restoreMutation = {
          type: "item.restore",
          sectionId: section.id,
          sectionKind: section.kind,
          item: section.items[itemIndex],
          index: itemIndex,
        };
        break;
      case "project":
        restoreMutation = {
          type: "item.restore",
          sectionId: section.id,
          sectionKind: section.kind,
          item: section.items[itemIndex],
          index: itemIndex,
        };
        break;
      case "publication":
        restoreMutation = {
          type: "item.restore",
          sectionId: section.id,
          sectionKind: section.kind,
          item: section.items[itemIndex],
          index: itemIndex,
        };
        break;
      case "achievement":
        restoreMutation = {
          type: "item.restore",
          sectionId: section.id,
          sectionKind: section.kind,
          item: section.items[itemIndex],
          index: itemIndex,
        };
        break;
    }

    onMutation({ type: "item.remove", sectionId: section.id, itemId });
    toast.info(t.itemDeleted, {
      id: `item-removed-${itemId}`,
      action: {
        label: t.undoAction,
        onClick: () => onMutation(restoreMutation),
      },
    });
  };
  const onUpdateItem = (mutation: ItemUpdateMutation) => onMutation(mutation);
  const onMoveItem = (itemId: string, direction: "up" | "down") => {
    onMutation({ type: "item.move", sectionId: section.id, itemId, direction });
  };

  switch (section.kind) {
    case "education":
      return (
        <EducationSectionEditor
          t={t}
          section={section}
          initiallyOpenItemId={initiallyOpenItemId}
          onUpdateItem={onUpdateItem}
          onRemoveItem={onRemoveItem}
          onMoveItem={onMoveItem}
        />
      );
    case "experience":
      return (
        <ExperienceSectionEditor
          t={t}
          section={section}
          initiallyOpenItemId={initiallyOpenItemId}
          onUpdateItem={onUpdateItem}
          onRemoveItem={onRemoveItem}
          onMoveItem={onMoveItem}
        />
      );
    case "project":
      return (
        <ProjectSectionEditor
          t={t}
          section={section}
          initiallyOpenItemId={initiallyOpenItemId}
          onUpdateItem={onUpdateItem}
          onRemoveItem={onRemoveItem}
          onMoveItem={onMoveItem}
        />
      );
    case "publication":
      return (
        <PublicationSectionEditor
          t={t}
          section={section}
          initiallyOpenItemId={initiallyOpenItemId}
          onUpdateItem={onUpdateItem}
          onRemoveItem={onRemoveItem}
          onMoveItem={onMoveItem}
        />
      );
    case "achievement":
      return (
        <AchievementSectionEditor
          t={t}
          section={section}
          initiallyOpenItemId={initiallyOpenItemId}
          onUpdateItem={onUpdateItem}
          onRemoveItem={onRemoveItem}
          onMoveItem={onMoveItem}
        />
      );
    case "simple_list":
      return (
        <SimpleListSectionEditor
          t={t}
          section={section}
          onUpdateItem={onUpdateItem}
        />
      );
  }
}
