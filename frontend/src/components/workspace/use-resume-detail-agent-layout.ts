import { useEffect, useState } from "react";

const AGENT_DOCK_MEDIA_QUERY = "(min-width: 1536px)";

/** Owns only responsive dock/sheet presentation state for the Agent panel. */
export function useResumeDetailAgentLayout() {
  const [isDockLayout, setIsDockLayout] = useState(() =>
    window.matchMedia(AGENT_DOCK_MEDIA_QUERY).matches,
  );
  const [isPanelCollapsed, setIsPanelCollapsed] = useState(false);
  const [isSheetOpen, setIsSheetOpen] = useState(false);

  useEffect(() => {
    const mediaQuery = window.matchMedia(AGENT_DOCK_MEDIA_QUERY);
    const syncLayout = () => {
      setIsDockLayout(mediaQuery.matches);
      if (mediaQuery.matches) {
        setIsSheetOpen(false);
      }
    };

    syncLayout();
    mediaQuery.addEventListener("change", syncLayout);
    return () => mediaQuery.removeEventListener("change", syncLayout);
  }, []);

  return {
    isDockLayout,
    isPanelCollapsed,
    isSheetOpen,
    setIsPanelCollapsed,
    setIsSheetOpen,
  };
}
