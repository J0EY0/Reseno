import { useCallback, useLayoutEffect, useRef } from "react";

export type EditorSectionNavigation = {
  sectionId: string;
  itemId?: string;
  requestId: number;
};

export function useEditorSectionNavigation(
  openSectionId: string | null,
  navigation?: EditorSectionNavigation,
) {
  const panelRef = useRef<HTMLElement>(null);
  const scrollPositions = useRef(new Map<string, number>());
  const activeSectionId = useRef(openSectionId);
  const lastRequestId = useRef<number | undefined>(undefined);
  const restoring = useRef(false);
  const cancelNavigation = useRef<(() => void) | null>(null);

  const rememberScroll = useCallback(() => {
    const panel = panelRef.current;
    if (panel && activeSectionId.current && !restoring.current) {
      scrollPositions.current.set(activeSectionId.current, panel.scrollTop);
    }
  }, []);

  const onInteraction = useCallback(() => {
    cancelNavigation.current?.();
    rememberScroll();
  }, [rememberScroll]);

  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!panel) return;
    activeSectionId.current = openSectionId;
    if (!navigation) lastRequestId.current = undefined;
    const requested =
      navigation &&
      navigation.requestId !== lastRequestId.current &&
      navigation.sectionId === openSectionId;
    if (requested) lastRequestId.current = navigation.requestId;
    const saved = openSectionId
      ? scrollPositions.current.get(openSectionId)
      : undefined;
    if (!openSectionId || (!requested && saved === undefined)) return;

    let cancelled = false;
    let frame = 0;
    let revision = 0;
    let stopScrolling: (() => void) | undefined;
    restoring.current = true;
    const stacked = getComputedStyle(panel).overflowY === "visible";
    const removeInteractionListeners = () => {
      if (requested && stacked) {
        document.removeEventListener("pointerdown", onInteraction, true);
        document.removeEventListener("keydown", onInteraction, true);
        document.removeEventListener("wheel", onInteraction, true);
      }
    };
    const findSection = () =>
      Array.from(
        panel.querySelectorAll<HTMLElement>("[data-editor-section-id]"),
      ).find((element) => element.dataset.editorSectionId === openSectionId);
    const findTarget = (section: HTMLElement) =>
      requested && navigation.itemId
        ? Array.from(
            section.querySelectorAll<HTMLElement>("[data-resume-item-id]"),
          ).find(
            (element) => element.dataset.resumeItemId === navigation.itemId,
          )
        : section;
    const restore = () => {
      if (cancelled) return;
      const section = findSection();
      const target = section && findTarget(section);
      if (!target || target.dataset.open === "false") return;
      if (requested) {
        const scroller = stacked ? window : panel;
        const events = stacked ? document : panel;
        const position = () => (stacked ? window.scrollY : panel.scrollTop);
        const top = stacked
          ? parseFloat(
              getComputedStyle(panel).getPropertyValue("--document-sticky-top"),
            ) || 0
          : panel.getBoundingClientRect().top;
        const maximum = stacked
          ? document.documentElement.scrollHeight - window.innerHeight
          : panel.scrollHeight - panel.clientHeight;
        const destination = Math.max(
          0,
          Math.min(
            maximum,
            position() + target.getBoundingClientRect().top - top,
          ),
        );
        const reducedMotion = window.matchMedia(
          "(prefers-reduced-motion: reduce)",
        ).matches;
        const smooth = !reducedMotion && Math.abs(destination - position()) > 1;
        if (smooth) {
          const removeListeners = () => {
            events.removeEventListener("scrollend", finish);
            removeInteractionListeners();
          };
          const finish = (event: Event) => {
            if (event.target !== events) return;
            removeListeners();
            stopScrolling = undefined;
            restoring.current = false;
            rememberScroll();
          };
          events.addEventListener("scrollend", finish);
          stopScrolling = () => {
            removeListeners();
            scroller.scrollTo({ top: position(), behavior: "instant" });
            stopScrolling = undefined;
          };
        }
        scroller.scrollTo({
          top: destination,
          behavior: smooth ? "smooth" : "instant",
        });
      } else {
        panel.scrollTop = saved!;
      }
    };
    const settle = async (currentRevision: number) => {
      const animations = panel
        .getAnimations({ subtree: true })
        .filter(
          (animation) =>
            animation.playState === "running" &&
            animation.effect?.getTiming().iterations !== Infinity,
        );
      await Promise.allSettled(
        animations.map((animation) => animation.finished),
      );
      if (cancelled || revision !== currentRevision) return;
      const section = findSection();
      const target = section && findTarget(section);
      if (
        section
          ?.querySelector('[data-slot="editor-toggle-trigger"]')
          ?.getAttribute("aria-expanded") === "true" &&
        !section.querySelector('[aria-busy="true"]') &&
        target &&
        target.dataset.open !== "false"
      ) {
        restore();
        observer.disconnect();
        if (!stopScrolling) {
          removeInteractionListeners();
          restoring.current = false;
          rememberScroll();
        }
      }
    };
    const schedule = () => {
      restoring.current = true;
      const currentRevision = ++revision;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (!requested) restore();
        void settle(currentRevision);
      });
    };
    const observer = new MutationObserver(schedule);
    observer.observe(panel, { childList: true, subtree: true });
    const cancel = () => {
      cancelled = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      removeInteractionListeners();
      stopScrolling?.();
      restoring.current = false;
      if (cancelNavigation.current === cancel) cancelNavigation.current = null;
    };
    cancelNavigation.current = cancel;
    if (requested && stacked) {
      document.addEventListener("pointerdown", onInteraction, true);
      document.addEventListener("keydown", onInteraction, true);
      document.addEventListener("wheel", onInteraction, {
        capture: true,
        passive: true,
      });
    }
    schedule();
    return cancel;
  }, [navigation, onInteraction, openSectionId, rememberScroll]);

  return { panelRef, onScroll: rememberScroll, onInteraction };
}
