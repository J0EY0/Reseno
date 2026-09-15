import {
  ArrowDown,
  ArrowUp,
  Award,
  Briefcase,
  FolderKanban,
  GraduationCap,
  List,
  LibraryBig,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import {
  lazy,
  startTransition,
  Suspense,
  useState,
  type ReactNode,
} from "react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type { AppMessages } from "@/i18n";
import type { ResumeSectionMutation } from "@/lib/resume-section-mutations";
import type { ResumeSection, SectionKind } from "@/types/resume";

import { EditorCardShell } from "./editor-card-shell";
import { useEditorSortable } from "./use-editor-sortable";

const sectionIcons: Record<SectionKind, LucideIcon> = {
  education: GraduationCap,
  experience: Briefcase,
  project: FolderKanban,
  publication: LibraryBig,
  achievement: Award,
  simple_list: List,
};

const ResumeSectionContent = lazy(() =>
  import("./resume-section-content").then((module) => ({
    default: module.ResumeSectionContent,
  })),
);

const ResumeSectionDeleteDialog = lazy(() =>
  import("./resume-section-delete-dialog").then((module) => ({
    default: module.ResumeSectionDeleteDialog,
  })),
);

type ResumeSectionCardProps = {
  t: AppMessages;
  documentT: AppMessages | null;
  section: ResumeSection;
  collapsed: boolean;
  onToggle: () => void;
  onMutation: (mutation: ResumeSectionMutation) => void;
  onRemoveSection: (sectionId: string) => void;
  onMoveSectionUp: (sectionId: string) => void;
  onMoveSectionDown: (sectionId: string) => void;
  canMoveUp: boolean;
  canMoveDown: boolean;
};

export function ResumeSectionCard({
  t,
  documentT,
  section,
  collapsed,
  onToggle,
  onMutation,
  onRemoveSection,
  onMoveSectionDown,
  onMoveSectionUp,
  canMoveUp,
  canMoveDown,
}: ResumeSectionCardProps) {
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const Icon = sectionIcons[section.kind];
  const sectionTitle =
    section.title.trim() || documentT?.sectionTitles[section.kind] || "";
  const { setNodeRef, style, isDragging, activator, move } = useEditorSortable(
    section.id,
    sectionTitle,
  );
  const itemLabel =
    section.items.length === 1 ? t.itemCountSingular : t.itemCount;
  const itemCountLabel = `${section.items.length} ${itemLabel}`;

  function renderCard(children: ReactNode) {
    return (
      <EditorCardShell
        sort={activator}
        icon={Icon}
        title={sectionTitle}
        titleMeta={itemCountLabel}
        toggleLabel={`${sectionTitle}: ${t.toggleSection}`}
        collapsed={collapsed}
        onToggle={() => startTransition(onToggle)}
        headerAction={
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              disabled={!canMoveUp}
              aria-label={`${sectionTitle}: ${t.moveSectionUp}`}
              onClick={(event) =>
                move(event.currentTarget, () => onMoveSectionUp(section.id))
              }
            >
              <ArrowUp aria-hidden="true" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              disabled={!canMoveDown}
              aria-label={`${sectionTitle}: ${t.moveSectionDown}`}
              onClick={(event) =>
                move(event.currentTarget, () => onMoveSectionDown(section.id))
              }
            >
              <ArrowDown aria-hidden="true" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`${sectionTitle}: ${t.deleteSection}`}
              onClick={(event) => {
                event.stopPropagation();
                setDeleteDialogOpen(true);
              }}
            >
              <Trash2 aria-hidden="true" />
            </Button>
            <Suspense fallback={null}>
              <ResumeSectionDeleteDialog
                open={deleteDialogOpen}
                sectionId={section.id}
                t={t}
                onOpenChange={setDeleteDialogOpen}
                onRemoveSection={onRemoveSection}
              />
            </Suspense>
          </div>
        }
      >
        {children}
      </EditorCardShell>
    );
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="editor-sortable"
      data-resume-section-id={section.id}
      data-dragging={isDragging || undefined}
    >
      <Suspense
        fallback={renderCard(
          <div aria-busy="true" className="flex justify-center py-4">
            <Spinner />
          </div>,
        )}
      >
        {renderCard(
          <ResumeSectionContent
            t={t}
            section={section}
            onMutation={onMutation}
          />,
        )}
      </Suspense>
    </div>
  );
}
