import { useLayoutEffect, useRef, type RefObject } from "react";

const animationId = "editor-reorder";

export function cancelEditorMoveAnimations(items: Iterable<HTMLElement>) {
  for (const item of items) {
    for (const animation of item.getAnimations()) {
      if (animation.id === animationId) animation.cancel();
    }
  }
}

function revealHeading(heading: HTMLElement, reducedMotion: boolean) {
  const editor = heading.closest<HTMLElement>(".resume-editor-panel");
  const scrollsInside = editor && getComputedStyle(editor).overflowY === "auto";
  const viewport = scrollsInside
    ? editor.getBoundingClientRect()
    : { top: 0, bottom: window.innerHeight };
  const rect = heading.getBoundingClientRect();
  const headerHeight = Number.parseFloat(
    getComputedStyle(heading).getPropertyValue("--document-sticky-top"),
  );
  const top = Math.max(headerHeight, viewport.top);
  const bottom = Math.min(window.innerHeight, viewport.bottom);
  const delta =
    rect.top < top
      ? rect.top - top
      : rect.bottom > bottom
        ? rect.bottom - bottom
        : 0;

  if (Math.abs(delta) < 1) return;
  (scrollsInside ? editor : window).scrollBy({
    top: delta,
    behavior: reducedMotion ? "instant" : "smooth",
  });
}

export function useEditorMove(
  index: number,
  node: RefObject<HTMLElement | null>,
) {
  const pendingMove = useRef<{
    button: HTMLButtonElement;
    positions: Map<HTMLElement, DOMRect>;
  } | null>(null);
  useLayoutEffect(() => {
    const pending = pendingMove.current;
    if (!pending) return;
    pendingMove.current = null;

    cancelEditorMoveAnimations(pending.positions.keys());

    const offsets = Array.from(pending.positions, ([item, before]) => ({
      item,
      y: before.top - item.getBoundingClientRect().top,
    }));
    const heading = node.current?.querySelector<HTMLElement>(
      '[data-slot="editor-sort-trigger"]',
    );
    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    (pending.button.disabled ? heading : pending.button)?.focus({
      preventScroll: true,
    });
    if (heading) revealHeading(heading, reducedMotion);

    if (reducedMotion) return;

    for (const { item, y } of offsets) {
      if (Math.abs(y) < 0.5) continue;
      const animation = item.animate(
        [{ transform: `translateY(${y}px)` }, { transform: "translateY(0)" }],
        { duration: 180, easing: "ease-out" },
      );
      animation.id = animationId;
    }
  }, [index, node]);

  return function move(button: HTMLButtonElement, update: () => void) {
    const parent = node.current?.parentElement;
    if (!parent) return;

    pendingMove.current = {
      button,
      positions: new Map(
        Array.from(
          parent.querySelectorAll<HTMLElement>(":scope > .editor-sortable"),
          (item) => [item, item.getBoundingClientRect()],
        ),
      ),
    };
    update();
  };
}
