import {
  useCallback,
  useLayoutEffect,
  useRef,
  type RefObject,
} from "react";

import type { ResumeDraftDiff } from "@/types/resume";

import {
  getResumeDraftReviewPaths,
  isVisibleResumeDraftReviewTarget,
} from "./resume-draft-review-dom";

export interface ResumeDraftReviewTarget {
  diff: ResumeDraftDiff;
  element: HTMLElement;
  reviewItemId?: string;
}

interface ReviewDecorationInputs {
  activeElement: HTMLElement | null;
  exitingReviewItemIds: ReadonlySet<string>;
  inspectLabel: string;
  resolveTarget: (
    element: HTMLElement | null,
  ) => ResumeDraftReviewTarget | null;
  selectedReviewItemId?: string;
}

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function isWithinDocumentCanvasViewport(element: HTMLElement) {
  const viewport = element.closest<HTMLElement>(
    '[data-slot="document-canvas-viewport"]',
  );
  if (!viewport) {
    return true;
  }

  const targetRect = element.getBoundingClientRect();
  const viewportRect = viewport.getBoundingClientRect();
  return (
    targetRect.top >= viewportRect.top &&
    targetRect.bottom <= viewportRect.bottom &&
    targetRect.left >= viewportRect.left &&
    targetRect.right <= viewportRect.right
  );
}

function getReviewOperationKey(target: ResumeDraftReviewTarget) {
  return JSON.stringify([
    target.reviewItemId ?? null,
    target.diff.operationId,
  ]);
}

function clearReviewTabStop(element: HTMLElement) {
  if (element.dataset.resumeReviewTabStop !== "true") {
    return;
  }
  element.removeAttribute("aria-label");
  element.removeAttribute("aria-controls");
  element.removeAttribute("aria-describedby");
  element.removeAttribute("aria-expanded");
  element.removeAttribute("aria-haspopup");
  element.removeAttribute("role");
  element.removeAttribute("tabindex");
  delete element.dataset.resumeReviewTabStop;
}

function clearReviewDecoration(element: HTMLElement) {
  element.classList.remove("resume-diff-review-target");
  delete element.dataset.resumeReviewDecorated;
  delete element.dataset.resumeReviewItemId;
  delete element.dataset.resumeReviewOperationId;
  delete element.dataset.resumeReviewState;
  clearReviewTabStop(element);
}

export function useResumeDraftReviewDecoration({
  activeElement,
  exitingReviewItemIds,
  inspectLabel,
  onPinnedTargetReplace,
  pinnedTargetRef,
  previewRef,
  resolveTarget,
  reviewPopoverId,
  selectedReviewItemId,
}: {
  activeElement: HTMLElement | null;
  exitingReviewItemIds: readonly string[];
  inspectLabel: string;
  onPinnedTargetReplace: (target: ResumeDraftReviewTarget | null) => void;
  pinnedTargetRef: RefObject<ResumeDraftReviewTarget | null>;
  previewRef: RefObject<HTMLElement | null>;
  resolveTarget: (
    element: HTMLElement | null,
  ) => ResumeDraftReviewTarget | null;
  reviewPopoverId: string;
  selectedReviewItemId?: string;
}) {
  const inputs: ReviewDecorationInputs = {
    activeElement,
    exitingReviewItemIds: new Set(exitingReviewItemIds),
    inspectLabel,
    resolveTarget,
    selectedReviewItemId,
  };
  const inputsRef = useRef(inputs);
  const decoratedElementsRef = useRef<Set<HTMLElement>>(new Set());
  const visibleOperationKeysRef = useRef<Set<string>>(new Set());
  const exitingOperationKeysRef = useRef<Set<string>>(new Set());
  const lastRevealedItemIdRef = useRef<string | null>(null);
  const observedRootRef = useRef<HTMLElement | null>(null);
  const observerRef = useRef<MutationObserver | null>(null);

  const reconcileReviewTargets = useCallback(
    (root: HTMLElement) => {
      const currentInputs = inputsRef.current;
      const targets = [...root.querySelectorAll<HTMLElement>(
        "[data-resume-diff-path]",
      )]
        .filter((element) => !element.closest("[inert]"))
        .map((element) => currentInputs.resolveTarget(element))
        .filter(
          (target): target is ResumeDraftReviewTarget => Boolean(target),
        );
      const targetElements = new Set(targets.map((target) => target.element));
      const visibleTargets = new Set(
        targets
          .filter((target) => isVisibleResumeDraftReviewTarget(target.element))
          .map((target) => target.element),
      );
      const topLevelTargets = new Set(
        targets
          .filter((target) => {
            let ancestor = target.element.parentElement?.closest<HTMLElement>(
              "[data-resume-diff-path]",
            );
            while (ancestor) {
              if (targetElements.has(ancestor)) {
                return false;
              }
              ancestor = ancestor.parentElement?.closest<HTMLElement>(
                "[data-resume-diff-path]",
              );
            }
            return visibleTargets.has(target.element);
          })
          .map((target) => target.element),
      );
      const nextVisibleOperationKeys = new Set(
        targets.map(getReviewOperationKey),
      );
      const nextExitingOperationKeys = new Set(
        targets
          .filter(
            (target) =>
              target.reviewItemId &&
              currentInputs.exitingReviewItemIds.has(target.reviewItemId),
          )
          .map(getReviewOperationKey),
      );
      const enteringOperationKeys = new Set<string>();
      if (!prefersReducedMotion()) {
        for (const operationKey of nextVisibleOperationKeys) {
          if (
            !visibleOperationKeysRef.current.has(operationKey) ||
            (exitingOperationKeysRef.current.has(operationKey) &&
              !nextExitingOperationKeys.has(operationKey))
          ) {
            enteringOperationKeys.add(operationKey);
          }
        }
      }

      for (const element of decoratedElementsRef.current) {
        if (!targetElements.has(element)) {
          clearReviewDecoration(element);
        }
      }

      for (const target of targets) {
        const { element } = target;
        const operationKey = getReviewOperationKey(target);
        const hasSameOperation =
          element.dataset.resumeReviewOperationId === target.diff.operationId &&
          element.dataset.resumeReviewItemId === target.reviewItemId;
        element.classList.add("resume-diff-review-target");
        element.dataset.resumeReviewDecorated = "true";
        element.dataset.resumeReviewOperationId = target.diff.operationId;
        if (target.reviewItemId) {
          element.dataset.resumeReviewItemId = target.reviewItemId;
        } else {
          delete element.dataset.resumeReviewItemId;
        }

        if (topLevelTargets.has(element)) {
          if (nextExitingOperationKeys.has(operationKey)) {
            element.dataset.resumeReviewState = "exiting";
          } else if (enteringOperationKeys.has(operationKey)) {
            element.dataset.resumeReviewState = "entering";
          } else if (
            element.dataset.resumeReviewState !== "entering" ||
            !hasSameOperation
          ) {
            delete element.dataset.resumeReviewState;
          }
          const expanded = currentInputs.activeElement === element;
          element.tabIndex = 0;
          element.setAttribute("role", "button");
          element.setAttribute(
            "aria-label",
            currentInputs.inspectLabel.replace("{label}", target.diff.label),
          );
          element.setAttribute("aria-controls", reviewPopoverId);
          element.setAttribute("aria-expanded", String(expanded));
          element.setAttribute("aria-haspopup", "dialog");
          if (expanded) {
            element.setAttribute("aria-describedby", reviewPopoverId);
          } else {
            element.removeAttribute("aria-describedby");
          }
          element.dataset.resumeReviewTabStop = "true";
        } else {
          delete element.dataset.resumeReviewState;
          clearReviewTabStop(element);
        }
      }

      decoratedElementsRef.current = targetElements;
      visibleOperationKeysRef.current = nextVisibleOperationKeys;
      exitingOperationKeysRef.current = nextExitingOperationKeys;

      const selectedItemId = currentInputs.selectedReviewItemId;
      if (!selectedItemId) {
        lastRevealedItemIdRef.current = null;
      } else if (lastRevealedItemIdRef.current !== selectedItemId) {
        const selectedElement = targets.find(
          (target) =>
            target.reviewItemId === selectedItemId &&
            visibleTargets.has(target.element),
        )?.element;
        if (selectedElement) {
          if (!isWithinDocumentCanvasViewport(selectedElement)) {
            selectedElement.scrollIntoView({
              behavior: "auto",
              block: "nearest",
              inline: "nearest",
            });
          }
          lastRevealedItemIdRef.current = selectedItemId;
        }
      }

      const pinned = pinnedTargetRef.current;
      if (
        pinned &&
        (!pinned.element.isConnected || !visibleTargets.has(pinned.element))
      ) {
        const pinnedHadFocus =
          pinned.element === root.ownerDocument.activeElement ||
          pinned.element.contains(root.ownerDocument.activeElement);
        const replacement = targets.find(
          (target) =>
            target.diff.operationId === pinned.diff.operationId &&
            target.reviewItemId === pinned.reviewItemId &&
            getResumeDraftReviewPaths(target.element).includes(
              pinned.diff.path,
            ) &&
            visibleTargets.has(target.element),
        );
        if (replacement?.element !== pinned.element) {
          pinnedTargetRef.current = replacement ?? null;
          onPinnedTargetReplace(replacement ?? null);
          if (replacement && pinnedHadFocus) {
            replacement.element.focus({ preventScroll: true });
          }
        }
      }
    },
    [onPinnedTargetReplace, pinnedTargetRef, reviewPopoverId],
  );

  const handleReviewAnimationFinish = useCallback((event: AnimationEvent) => {
    if (
      event.animationName === "resume-diff-review-enter" &&
      event.target instanceof HTMLElement &&
      event.target.dataset.resumeReviewState === "entering"
    ) {
      delete event.target.dataset.resumeReviewState;
    }
  }, []);

  const stopObservingReviewRoot = useCallback(
    (resetOperations: boolean) => {
      observerRef.current?.disconnect();
      observerRef.current = null;
      const root = observedRootRef.current;
      if (root) {
        root.removeEventListener(
          "animationend",
          handleReviewAnimationFinish,
          true,
        );
        root.removeEventListener(
          "animationcancel",
          handleReviewAnimationFinish,
          true,
        );
      }
      for (const element of decoratedElementsRef.current) {
        clearReviewDecoration(element);
      }
      decoratedElementsRef.current = new Set();
      observedRootRef.current = null;
      if (resetOperations) {
        visibleOperationKeysRef.current = new Set();
        exitingOperationKeysRef.current = new Set();
      }
    },
    [handleReviewAnimationFinish],
  );

  useLayoutEffect(() => {
    inputsRef.current = inputs;
    const root = previewRef.current;
    if (observedRootRef.current !== root) {
      stopObservingReviewRoot(false);
      observedRootRef.current = root;
      if (root) {
        const observer = new MutationObserver(() => {
          if (observedRootRef.current === root) {
            reconcileReviewTargets(root);
          }
        });
        observer.observe(root, { childList: true, subtree: true });
        observerRef.current = observer;
        root.addEventListener(
          "animationend",
          handleReviewAnimationFinish,
          true,
        );
        root.addEventListener(
          "animationcancel",
          handleReviewAnimationFinish,
          true,
        );
      }
    }
    if (root) {
      reconcileReviewTargets(root);
    }
  });

  useLayoutEffect(
    () => () => stopObservingReviewRoot(true),
    [stopObservingReviewRoot],
  );
}
