import { useCallback, useState } from "react";

import type { AgentPanelStatus } from "@/components/copilot/copilot-panel-types";

const AGENT_AUTO_EXPAND_MEDIA_QUERY = "(min-width: 1536px)";

/** Owns the single collapsed state for the inline Agent panel. */
export function useResumeDetailAgentLayout(resumeId: string | undefined) {
  const [isPanelCollapsed, setIsPanelCollapsed] = useState(
    () =>
      !window.matchMedia(AGENT_AUTO_EXPAND_MEDIA_QUERY).matches,
  );
  const [reportedStatus, setReportedStatus] = useState<{
    resumeId: string | undefined;
    status: AgentPanelStatus;
  } | null>(null);
  const reportPanelStatus = useCallback(
    (status: AgentPanelStatus) => {
      setReportedStatus((current) =>
        current && current.resumeId === resumeId && current.status === status
          ? current
          : { resumeId, status },
      );
    },
    [resumeId],
  );
  const panelStatus =
    reportedStatus && reportedStatus.resumeId === resumeId
      ? reportedStatus.status
      : null;

  return {
    isPanelCollapsed,
    panelStatus,
    reportPanelStatus,
    setIsPanelCollapsed,
  };
}
