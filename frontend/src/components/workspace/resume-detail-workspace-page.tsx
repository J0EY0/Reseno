import { useLayoutEffect, useState } from "react";
import { useLocation, useNavigationType, useParams } from "react-router-dom";

import { ResumeDetailWorkspaceView } from "@/components/workspace/resume-detail-workspace-view";
import { useResumeDetailWorkspace } from "@/components/workspace/use-resume-detail-workspace";
import { useWorkspacePreferences } from "@/components/workspace/workspace-preferences-context";
import {
  clearWorkspaceRouteHistoryState,
  releaseWorkspaceRouteHandoff,
} from "@/lib/workspace-route-handoff";

interface ResumeDetailRouteOwnerProps {
  onLogout: () => void;
  resumeId: string;
  routeState: unknown;
}

function ResumeDetailRouteOwner({
  onLogout,
  resumeId,
  routeState,
}: ResumeDetailRouteOwnerProps) {
  const {
    locale,
    messages,
    changeLocale: onLocaleChange,
  } = useWorkspacePreferences();
  const location = useLocation();
  const navigationType = useNavigationType();
  const [initialRouteState] = useState(routeState);

  useLayoutEffect(() => {
    if (navigationType !== "PUSH") {
      return;
    }

    window.scrollTo({ left: 0, top: 0, behavior: "auto" });
    document.getElementById("main-content")?.focus({ preventScroll: true });
  }, [navigationType]);

  useLayoutEffect(() => {
    if (routeState == null) {
      return;
    }

    // Keep the seed for this mount, but do not let browser history resurrect
    // it after a newer checkpoint has become the server authority.
    releaseWorkspaceRouteHandoff(routeState);
    clearWorkspaceRouteHistoryState(location.key);
  }, [location.key, routeState]);

  const workspace = useResumeDetailWorkspace({
    locale,
    messages,
    onLogout,
    resumeId,
    routeState: initialRouteState,
  });

  return (
    <ResumeDetailWorkspaceView
      locale={locale}
      messages={messages}
      model={workspace.model}
      onLocaleChange={onLocaleChange}
      previewRef={workspace.previewRef}
    />
  );
}

/** Remounts transaction refs when React Router reuses the detail element. */
export function ResumeDetailWorkspacePage({
  onLogout,
}: {
  onLogout: () => void;
}) {
  const location = useLocation();
  const { id = "" } = useParams<{ id: string }>();

  return (
    <ResumeDetailRouteOwner
      key={id}
      onLogout={onLogout}
      resumeId={id}
      routeState={location.state}
    />
  );
}
