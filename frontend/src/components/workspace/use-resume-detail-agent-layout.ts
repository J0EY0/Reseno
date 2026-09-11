import { useCallback, useState } from "react";

import type { AgentPanelStatus } from "@/components/copilot/copilot-panel-types";

import {
  readWorkspaceLayoutPreference,
  writeWorkspaceLayoutPreference,
} from "@/components/workspace/resume-workspace-layout";

const AGENT_AUTO_EXPAND_MEDIA_QUERY = "(min-width: 1536px)";

/** Owns the single collapsed state for the inline Agent panel. */
export function useResumeDetailAgentLayout(resumeId: string | undefined) {
  const [isPanelCollapsed, setCollapsed] = useState(
    () =>
      readWorkspaceLayoutPreference().agentCollapsed ??
      !window.matchMedia(AGENT_AUTO_EXPAND_MEDIA_QUERY).matches,
  );
  const setIsPanelCollapsed = useCallback((collapsed: boolean) => {
    setCollapsed(collapsed);
    writeWorkspaceLayoutPreference({ agentCollapsed: collapsed });
  }, []);
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
