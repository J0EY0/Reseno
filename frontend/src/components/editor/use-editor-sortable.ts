import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { CSSProperties, SyntheticEvent } from "react";

import {
  cancelEditorMoveAnimations,
  useEditorMove,
} from "@/components/editor/use-editor-move";
import { useWorkspacePreferences } from "@/components/workspace/workspace-preferences-context";
import { editorSortingMessages } from "@/i18n/editor-sorting";

export type EditorSortActivator = Pick<
  ReturnType<typeof useSortable>,
  "setActivatorNodeRef" | "attributes" | "listeners"
>;

export function useEditorSortable(id: string, label: string) {
  const { locale } = useWorkspacePreferences();
  const {
    setNodeRef,
    setActivatorNodeRef,
    attributes,
    listeners,
    transform,
    transition,
    isDragging,
    index,
    node,
  } = useSortable({
    id,
    data: { label },
    attributes: { roleDescription: editorSortingMessages[locale].role },
    transition: { duration: 160, easing: "ease" },
  });
  const move = useEditorMove(index, node);
  const sortListeners = Object.fromEntries(
    Object.entries(listeners ?? {}).map(([eventName, listener]) => [
      eventName,
      (event: SyntheticEvent<HTMLElement>) => {
        const editor = event.currentTarget.closest(".resume-editor-panel");
        if (editor) {
          cancelEditorMoveAnimations(
            editor.querySelectorAll<HTMLElement>(".editor-sortable"),
          );
        }
        listener(event);
      },
    ]),
  );

  const style: CSSProperties = {
    transform: CSS.Translate.toString(transform),
    transition,
  };

  return {
    setNodeRef,
    style,
    isDragging,
    move,
    activator: { setActivatorNodeRef, attributes, listeners: sortListeners },
  };
}
