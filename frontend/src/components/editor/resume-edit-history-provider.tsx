import {
  useEffect,
  useEffectEvent,
  useRef,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import {
  ResumeEditHistoryContext,
  type ResumeEditHistory,
} from "./resume-edit-history-context";

function belongsToScope(target: EventTarget | null, scope: HTMLElement) {
  return (
    target instanceof Element &&
    scope.contains(target) &&
    !target.closest("[inert]")
  );
}

export function ResumeEditHistoryProvider({
  value,
  onBreakHistoryGroup,
  children,
}: {
  value: ResumeEditHistory;
  onBreakHistoryGroup?: () => void;
  children: ReactNode;
}) {
  const scopeRef = useRef<HTMLDivElement>(null);
  const beforeInput = useEffectEvent((event: InputEvent) => {
    const scope = scopeRef.current;
    if (
      !scope ||
      !belongsToScope(event.target, scope) ||
      event.defaultPrevented ||
      event.isComposing
    ) {
      return;
    }
    if (
      event.inputType === "historyUndo" ||
      event.inputType === "historyRedo"
    ) {
      event.preventDefault();
      event.stopPropagation();
      onBreakHistoryGroup?.();
      if (event.inputType === "historyUndo" && value.canUndo) value.undo();
      if (event.inputType === "historyRedo" && value.canRedo) value.redo();
    } else if (
      event.inputType === "insertFromPaste" ||
      event.inputType === "insertFromDrop"
    ) {
      onBreakHistoryGroup?.();
    }
  });

  useEffect(() => {
    const scope = scopeRef.current;
    if (!scope) return;
    const handleBeforeInput = (event: InputEvent) => beforeInput(event);
    scope.addEventListener("beforeinput", handleBeforeInput, true);
    return () =>
      scope.removeEventListener("beforeinput", handleBeforeInput, true);
  }, []);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (
      !belongsToScope(event.target, event.currentTarget) ||
      event.defaultPrevented ||
      event.nativeEvent.isComposing ||
      event.altKey ||
      !(event.metaKey || event.ctrlKey)
    ) {
      return;
    }
    const key = event.key.toLowerCase();
    const undo = key === "z" && !event.shiftKey;
    const redo = (key === "z" && event.shiftKey) || key === "y";
    if (!undo && !redo) {
      onBreakHistoryGroup?.();
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    onBreakHistoryGroup?.();
    if (undo && value.canUndo) value.undo();
    if (redo && value.canRedo) value.redo();
  }

  return (
    <ResumeEditHistoryContext value={value}>
      <div
        ref={scopeRef}
        className="contents"
        data-resume-edit-history-scope=""
        onKeyDownCapture={handleKeyDown}
        onFocusCapture={onBreakHistoryGroup}
        onBlurCapture={onBreakHistoryGroup}
        onClickCapture={onBreakHistoryGroup}
        onPasteCapture={onBreakHistoryGroup}
        onDropCapture={onBreakHistoryGroup}
      >
        {children}
      </div>
    </ResumeEditHistoryContext>
  );
}
