import { useLayoutEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { ResumeDetailWorkspaceView } from "@/components/workspace/resume-detail-workspace-view";
import { useResumeDetailWorkspace } from "@/components/workspace/use-resume-detail-workspace";
import type { AppMessages, Locale } from "@/i18n";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";

interface ResumeDetailRouteOwnerProps {
  locale: Locale;
  messages: AppMessages;
  onLocaleChange: (locale: Locale) => void;
  onLogout: () => void;
  persistence: WorkspacePreferencesPersistence;
  resumeId: string;
  routeState: unknown;
}

function ResumeDetailRouteOwner({
  locale,
  messages,
  onLocaleChange,
  onLogout,
  persistence,
  resumeId,
  routeState,
}: ResumeDetailRouteOwnerProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const [initialRouteState] = useState(routeState);

  useLayoutEffect(() => {
    if (routeState == null) {
      return;
    }

    // Keep the seed for this mount, but do not let browser history resurrect
    // it after a newer checkpoint has become the server authority.
    navigate(
      {
        hash: location.hash,
        pathname: location.pathname,
        search: location.search,
      },
      { replace: true, state: null },
    );
  }, [location.hash, location.pathname, location.search, navigate, routeState]);

  const workspace = useResumeDetailWorkspace({
    locale,
    messages,
    onLocaleChange,
    onLogout,
    persistence,
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
  locale,
  messages,
  onLocaleChange,
  onLogout,
  persistence,
}: {
  locale: Locale;
  messages: AppMessages;
  onLocaleChange: (locale: Locale) => void;
  onLogout: () => void;
  persistence: WorkspacePreferencesPersistence;
}) {
  const location = useLocation();
  const { id = "" } = useParams<{ id: string }>();

  return (
    <ResumeDetailRouteOwner
      key={id}
      locale={locale}
      messages={messages}
      onLocaleChange={onLocaleChange}
      onLogout={onLogout}
      persistence={persistence}
      resumeId={id}
      routeState={location.state}
    />
  );
}
