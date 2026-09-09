import { useLayoutEffect, useRef } from "react";
import type { StickToBottomContext } from "use-stick-to-bottom";

/** Keeps the overlaid composer and the conversation safe area in lockstep. */
export function useAgentComposerLayout() {
  const composerRef = useRef<HTMLElement | null>(null);
  const conversationLayoutRef = useRef<HTMLDivElement | null>(null);
  const conversationContextRef = useRef<StickToBottomContext | null>(null);

  useLayoutEffect(() => {
    const composer = composerRef.current;
    const conversationLayout = conversationLayoutRef.current;

    if (!composer || !conversationLayout) {
      return;
    }

    let previousHeight = -1;
    const syncComposerHeight = () => {
      const nextHeight = composer.getBoundingClientRect().height;

      if (nextHeight === previousHeight) {
        return;
      }

      const conversation = conversationContextRef.current;
      const shouldFollowBottom = Boolean(
        conversation?.state.isAtBottom && !conversation.state.escapedFromLock,
      );

      previousHeight = nextHeight;
      conversationLayout.style.setProperty(
        "--agent-composer-height",
        `${nextHeight}px`,
      );
      conversationLayout.style.setProperty(
        "--agent-composer-midpoint",
        `${nextHeight / 2}px`,
      );

      // Read the lock before changing the safe area: the layout mutation can
      // temporarily make an attached conversation appear away from the bottom.
      if (shouldFollowBottom) {
        void conversation?.scrollToBottom({ animation: "instant" });
      }
    };

    syncComposerHeight();
    const resizeObserver = new ResizeObserver(syncComposerHeight);
    resizeObserver.observe(composer);
    return () => resizeObserver.disconnect();
  }, []);

  return { composerRef, conversationContextRef, conversationLayoutRef };
}
