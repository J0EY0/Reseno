import { createContext, useContext } from "react";

export interface ResumeEditHistory {
  canUndo: boolean;
  canRedo: boolean;
  undo: () => void;
  redo: () => void;
}

export const ResumeEditHistoryContext = createContext<ResumeEditHistory | null>(
  null,
);

export function useResumeEditHistory() {
  const history = useContext(ResumeEditHistoryContext);
  if (!history) {
    throw new Error(
      "Resume editors must be used within ResumeEditHistoryProvider.",
    );
  }
  return history;
}
