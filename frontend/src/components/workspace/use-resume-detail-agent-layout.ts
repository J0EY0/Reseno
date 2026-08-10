import { useState } from "react";

const AGENT_AUTO_EXPAND_MEDIA_QUERY = "(min-width: 1536px)";

/** Owns the single collapsed state for the inline Agent panel. */
export function useResumeDetailAgentLayout() {
  const [isPanelCollapsed, setIsPanelCollapsed] = useState(
    () =>
      !window.matchMedia(AGENT_AUTO_EXPAND_MEDIA_QUERY).matches,
  );

  return {
    isPanelCollapsed,
    setIsPanelCollapsed,
  };
}
