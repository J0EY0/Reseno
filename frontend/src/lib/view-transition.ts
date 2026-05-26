import * as React from "react";
import { startTransition } from "react";

type TransitionType = "nav-forward" | "nav-back" | "nav-lateral";

const addTransitionType = (
  React as unknown as {
    addTransitionType?: (type: TransitionType) => void;
  }
).addTransitionType;

export function runViewTransition(
  scope: () => void,
  transitionType?: TransitionType,
) {
  startTransition(() => {
    if (transitionType) {
      addTransitionType?.(transitionType);
    }

    scope();
  });
}

