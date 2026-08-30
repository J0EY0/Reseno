import {
  lazy,
  memo,
  startTransition,
  Suspense,
  useState,
  type ChangeEvent,
  type Dispatch,
  type SetStateAction,
} from "react";

import { AddSectionPopover } from "@/components/editor/add-section-popover";
import { BasicInfoCard } from "@/components/editor/basic-info-card";
import { ResumeSectionCard } from "@/components/editor/resume-section-card";
import { Card, CardContent } from "@/components/ui/card";
import { WorkspacePanelSkeleton } from "@/components/workspace-skeletons";
import type { AppMessages } from "@/i18n";
import { readAvatarFileAsDataUrl } from "@/lib/avatar";
import { createId } from "@/lib/resume";
import {
  applySectionMutation,
  type ResumeSectionMutation,
} from "@/lib/resume-section-mutations";
import { createResumeSection } from "@/lib/resume-sections";
import type {
  CustomField,
  ResumeBasicInfo,
  ResumeData,
  SectionKind,
} from "@/types/resume";

type CollapsedState = Record<string, boolean>;

const AvatarCropDialog = lazy(() =>
  import("@/components/editor/avatar-crop-dialog").then((module) => ({
    default: module.AvatarCropDialog,
  })),
);

// The route controller owns persisted resume and navigation state. This pane
// owns only transient avatar UI and translates editor actions into state updates.
type ResumeEditorPaneProps = {
  t: AppMessages;
  resume: ResumeData;
  setResume: Dispatch<SetStateAction<ResumeData>>;
  collapsedState: CollapsedState;
  setCollapsedState: Dispatch<SetStateAction<CollapsedState>>;
  hasLoadError: boolean;
  showSkeleton: boolean;
};

function collapseAllExcept(current: CollapsedState, openId: string) {
  return Object.keys({ ...current, [openId]: false }).reduce(
    (state, key) => {
      state[key] = key !== openId;
      return state;
    },
    {} as CollapsedState,
  );
}

export const ResumeEditorPane = memo(function ResumeEditorPane({
  t,
  resume,
  setResume,
  collapsedState,
  setCollapsedState,
  hasLoadError,
  showSkeleton,
}: ResumeEditorPaneProps) {
  const [avatarCropSource, setAvatarCropSource] = useState<string | null>(null);

  function updateBasic<K extends keyof ResumeBasicInfo>(
    field: K,
    value: ResumeBasicInfo[K],
  ) {
    setResume((current) => ({
      ...current,
      basic: { ...current.basic, [field]: value },
    }));
  }

  function updateCustomField<K extends keyof Omit<CustomField, "id">>(
    id: string,
    field: K,
    value: CustomField[K],
  ) {
    setResume((current) => ({
      ...current,
      basic: {
        ...current.basic,
        customFields: current.basic.customFields.map((item) =>
          item.id === id ? { ...item, [field]: value } : item,
        ),
      },
    }));
  }

  function addCustomField() {
    startTransition(() => {
      setResume((current) => ({
        ...current,
        basic: {
          ...current.basic,
          customFields: [
            ...current.basic.customFields,
            { id: createId("field"), type: "text", label: "", value: "" },
          ],
        },
      }));
    });
  }

  function removeCustomField(id: string) {
    startTransition(() => {
      setResume((current) => ({
        ...current,
        basic: {
          ...current.basic,
          customFields: current.basic.customFields.filter(
            (field) => field.id !== id,
          ),
        },
      }));
    });
  }

  async function handleAvatarUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];

    if (!file) {
      return;
    }

    try {
      setAvatarCropSource(await readAvatarFileAsDataUrl(file));
    } finally {
      event.target.value = "";
    }
  }

  function mutateResumeSection(mutation: ResumeSectionMutation) {
    setResume((current) => {
      const result = applySectionMutation(current.sections, mutation);

      // A rejected mutation is atomic: stale UI state must never partially
      // modify the resume that the persistence layer will later snapshot.
      if (result.status !== "applied") {
        return current;
      }

      return { ...current, sections: result.sections };
    });
  }

  function removeSection(sectionId: string) {
    setResume((current) => ({
      ...current,
      sections: current.sections.filter((section) => section.id !== sectionId),
    }));
    setCollapsedState((current) => {
      const nextState = { ...current };
      delete nextState[sectionId];
      return nextState;
    });
  }

  function moveSection(sectionId: string, direction: "up" | "down") {
    startTransition(() => {
      setResume((current) => {
        const currentIndex = current.sections.findIndex(
          (section) => section.id === sectionId,
        );

        if (currentIndex < 0) {
          return current;
        }

        const targetIndex =
          direction === "up" ? currentIndex - 1 : currentIndex + 1;

        if (targetIndex < 0 || targetIndex >= current.sections.length) {
          return current;
        }

        const nextSections = [...current.sections];
        const [targetSection] = nextSections.splice(currentIndex, 1);
        nextSections.splice(targetIndex, 0, targetSection);

        return { ...current, sections: nextSections };
      });
    });
  }

  function addResumeSection(kind: SectionKind) {
    const nextSection = createResumeSection(kind);

    startTransition(() => {
      setResume((current) => ({
        ...current,
        sections: [...current.sections, nextSection],
      }));
    });

    setCollapsedState((current) => collapseAllExcept(current, nextSection.id));
  }

  function toggleCollapse(id: string) {
    setCollapsedState((current) => {
      if (current[id] === false) {
        return { ...current, [id]: true };
      }

      return collapseAllExcept(current, id);
    });
  }

  return (
    <>
      <Suspense fallback={null}>
        <AvatarCropDialog
          t={t}
          open={Boolean(avatarCropSource)}
          source={avatarCropSource}
          onCancel={() => setAvatarCropSource(null)}
          onConfirm={(value) => {
            updateBasic("avatar", value);
            setAvatarCropSource(null);
          }}
        />
      </Suspense>

      <section className="resume-editor-panel flex flex-col gap-2.5 print:hidden">
        {hasLoadError ? (
          <Card className="border-border/80">
            <CardContent className="p-5 text-sm text-muted-foreground">
              {t.loadError}
            </CardContent>
          </Card>
        ) : null}

        {showSkeleton ? (
          <WorkspacePanelSkeleton />
        ) : (
          <>
            <BasicInfoCard
              t={t}
              basic={resume.basic}
              collapsed={Boolean(collapsedState.basic)}
              onToggle={() => toggleCollapse("basic")}
              onUpdateBasic={updateBasic}
              onUpdateCustomField={updateCustomField}
              onAddCustomField={addCustomField}
              onRemoveCustomField={removeCustomField}
              onAvatarUpload={handleAvatarUpload}
              onRemoveAvatar={() => updateBasic("avatar", "")}
            />

            {resume.sections.map((section) => (
              <ResumeSectionCard
                key={section.id}
                t={t}
                section={section}
                canMoveUp={resume.sections[0]?.id !== section.id}
                canMoveDown={
                  resume.sections[resume.sections.length - 1]?.id !== section.id
                }
                collapsed={Boolean(collapsedState[section.id])}
                onToggle={() => toggleCollapse(section.id)}
                onMutation={mutateResumeSection}
                onRemoveSection={removeSection}
                onMoveSectionUp={(sectionId) => moveSection(sectionId, "up")}
                onMoveSectionDown={(sectionId) => moveSection(sectionId, "down")}
              />
            ))}

            <AddSectionPopover t={t} onSelect={addResumeSection} />
          </>
        )}
      </section>
    </>
  );
});
