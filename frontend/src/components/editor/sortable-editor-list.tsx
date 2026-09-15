import {
  closestCenter,
  DndContext,
  DragOverlay,
  KeyboardSensor,
  MouseSensor,
  pointerWithin,
  TouchSensor,
  useSensor,
  useSensors,
  type CollisionDetection,
} from "@dnd-kit/core";
import { restrictToVerticalAxis, snapCenterToCursor } from "@dnd-kit/modifiers";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { useWorkspacePreferences } from "@/components/workspace/workspace-preferences-context";
import { editorSortingMessages } from "@/i18n/editor-sorting";

const detectCollision: CollisionDetection = (args) => {
  const pointerCollisions = pointerWithin(args);
  return pointerCollisions.length > 0 ? pointerCollisions : closestCenter(args);
};

export function SortableEditorList({
  items,
  onReorder,
  children,
}: {
  items: string[];
  onReorder: (id: string, overId: string) => void;
  children: ReactNode;
}) {
  const { locale } = useWorkspacePreferences();
  const messages = editorSortingMessages[locale];
  const [activeLabel, setActiveLabel] = useState<string | null>(null);
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, {
      activationConstraint: { delay: 250, tolerance: 5 },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
      scrollBehavior: "auto",
      keyboardCodes: {
        start: ["Space"],
        cancel: ["Escape"],
        end: ["Space", "Enter", "Tab"],
      },
    }),
  );

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={detectCollision}
      modifiers={[restrictToVerticalAxis]}
      accessibility={{
        screenReaderInstructions: { draggable: messages.instructions },
        announcements: {
          onDragStart: ({ active }) =>
            messages.started(active.data.current?.label ?? ""),
          onDragOver: ({ over }) =>
            over
              ? messages.moved(items.indexOf(String(over.id)) + 1, items.length)
              : undefined,
          onDragEnd: ({ active, over }) =>
            over
              ? messages.dropped(
                  active.data.current?.label ?? "",
                  items.indexOf(String(over.id)) + 1,
                  items.length,
                )
              : messages.cancelled,
          onDragCancel: () => messages.cancelled,
        },
      }}
      onDragStart={({ active }) =>
        setActiveLabel(active.data.current?.label ?? "")
      }
      onDragCancel={() => setActiveLabel(null)}
      onDragEnd={({ active, over }) => {
        setActiveLabel(null);
        if (over && active.id !== over.id) {
          onReorder(String(active.id), String(over.id));
        }
      }}
    >
      <SortableContext items={items} strategy={verticalListSortingStrategy}>
        {children}
      </SortableContext>
      {createPortal(
        <DragOverlay dropAnimation={null} modifiers={[snapCenterToCursor]}>
          {activeLabel !== null ? (
            <div
              data-slot="editor-drag-overlay"
              className="truncate cursor-grabbing rounded-lg border border-primary/30 bg-card px-4 py-3 text-sm font-medium text-card-foreground shadow-lg"
            >
              {activeLabel}
            </div>
          ) : null}
        </DragOverlay>,
        document.body,
      )}
    </DndContext>
  );
}
