import { useLayoutEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { TemplateDetailWorkspaceView } from "@/components/workspace/template-detail-workspace-view";
import { useTemplateDetailWorkspace } from "@/components/workspace/use-template-detail-workspace";
import type { AppMessages, Locale } from "@/i18n";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";

interface TemplateDetailRouteOwnerProps {
  locale: Locale;
  messages: AppMessages;
  onLocaleChange: (locale: Locale) => void;
  onLogout: () => void;
  persistence: WorkspacePreferencesPersistence;
  routeState: unknown;
  templateId: string;
}

function TemplateDetailRouteOwner({
  locale,
  messages,
  onLocaleChange,
  onLogout,
  persistence,
  routeState,
  templateId,
}: TemplateDetailRouteOwnerProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const [initialRouteState] = useState(routeState);

  useLayoutEffect(() => {
    if (routeState == null) {
      return;
    }

    navigate(
      {
        hash: location.hash,
        pathname: location.pathname,
        search: location.search,
      },
      { replace: true, state: null },
    );
  }, [location.hash, location.pathname, location.search, navigate, routeState]);

  const controller = useTemplateDetailWorkspace({
    locale,
    messages,
    onLocaleChange,
    onLogout,
    persistence,
    routeState: initialRouteState,
    templateId,
  });

  return (
    <TemplateDetailWorkspaceView
      controller={controller}
      locale={locale}
      messages={messages}
      onLocaleChange={onLocaleChange}
    />
  );
}

/** Binds the route parameter and one-time handoff to the template workspace. */
export function TemplateDetailWorkspacePage({
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
    <TemplateDetailRouteOwner
      key={id}
      locale={locale}
      messages={messages}
      onLocaleChange={onLocaleChange}
      onLogout={onLogout}
      persistence={persistence}
      routeState={location.state}
      templateId={id}
    />
  );
}
