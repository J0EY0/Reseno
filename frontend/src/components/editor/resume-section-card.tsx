import {
  ArrowDown,
  ArrowUp,
  Award,
  Briefcase,
  Ellipsis,
  FolderKanban,
  GraduationCap,
  List,
  LibraryBig,
  type LucideIcon,
} from "lucide-react";
import {
  lazy,
  startTransition,
  Suspense,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type { AppMessages } from "@/i18n";
import type { ResumeSectionMutation } from "@/lib/resume-section-mutations";
import type { ResumeSection, SectionKind } from "@/types/resume";

import { EditorCardShell } from "./editor-card-shell";
import type { ResumeSectionAction } from "./resume-section-actions";
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

const loadResumeSectionActions = () =>
  import("./resume-section-actions").then((module) => ({
    default: module.ResumeSectionActions,
  }));
const ResumeSectionActions = lazy(loadResumeSectionActions);

function preloadResumeSectionActions() {
  void loadResumeSectionActions().catch(() => undefined);
}

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
  const [actionsRequested, setActionsRequested] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [action, setAction] = useState<ResumeSectionAction>(null);
  const pendingActionRef = useRef<ResumeSectionAction>(null);
  const focusFirstItemRef = useRef(false);
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

  function openActions(keyboard: boolean) {
    focusFirstItemRef.current = keyboard;
    startTransition(() => {
      setActionsRequested(true);
      setMenuOpen(true);
    });
  }

  function cancelActions() {
    setActionsRequested(false);
    setMenuOpen(false);
  }

  const actionsTrigger = (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      aria-label={`${sectionTitle}: ${t.moreActions}`}
      aria-haspopup="menu"
      aria-expanded={menuOpen}
      title={t.moreActions}
      onPointerEnter={preloadResumeSectionActions}
      onFocus={preloadResumeSectionActions}
      onBlur={cancelActions}
      onClick={(event) => openActions(event.detail === 0)}
      onKeyDown={(event) => {
        if (["Enter", " ", "ArrowDown"].includes(event.key)) {
          event.preventDefault();
          openActions(true);
        } else if (event.key === "Escape") {
          cancelActions();
        }
      }}
    >
      <Ellipsis aria-hidden="true" />
    </Button>
  );

  function renderCard(children: ReactNode) {
    return (
      <EditorCardShell
        sort={activator}
        icon={Icon}
        title={sectionTitle}
        titleMeta={section.kind === "simple_list" ? undefined : itemCountLabel}
        toggleLabel={`${sectionTitle}: ${t.toggleSection}`}
        collapsed={collapsed}
        onToggle={() => startTransition(onToggle)}
        headerAction={
          <div className="flex items-center">
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
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
              size="icon-sm"
              disabled={!canMoveDown}
              aria-label={`${sectionTitle}: ${t.moveSectionDown}`}
              onClick={(event) =>
                move(event.currentTarget, () => onMoveSectionDown(section.id))
              }
            >
              <ArrowDown aria-hidden="true" />
            </Button>
            <Suspense fallback={actionsTrigger}>
              {actionsRequested ? (
                <ResumeSectionActions
                  t={t}
                  section={section}
                  sectionTitle={sectionTitle}
                  onMutation={onMutation}
                  onRemoveSection={onRemoveSection}
                  menuOpen={menuOpen}
                  onMenuOpenChange={setMenuOpen}
                  action={action}
                  onActionChange={setAction}
                  pendingActionRef={pendingActionRef}
                  focusFirstItemRef={focusFirstItemRef}
                />
              ) : (
                actionsTrigger
              )}
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
