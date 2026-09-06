import { useLayoutEffect, useState } from "react";
import {
  useLocation,
  useNavigate,
  useNavigationType,
  useParams,
} from "react-router-dom";

import { TemplateDetailWorkspaceView } from "@/components/workspace/template-detail-workspace-view";
import { useTemplateDetailWorkspace } from "@/components/workspace/use-template-detail-workspace";
import { useWorkspacePreferences } from "@/components/workspace/workspace-preferences-context";

interface TemplateDetailRouteOwnerProps {
  onLogout: () => void;
  routeState: unknown;
  templateId: string;
}

function TemplateDetailRouteOwner({
  onLogout,
  routeState,
  templateId,
}: TemplateDetailRouteOwnerProps) {
  const { locale, messages, changeLocale: onLocaleChange } = useWorkspacePreferences();
  const location = useLocation();
  const navigate = useNavigate();
  const navigationType = useNavigationType();
  const [initialRouteState] = useState(routeState);

  useLayoutEffect(() => {
    if (navigationType !== "PUSH") {
      return;
    }

    window.scrollTo({ left: 0, top: 0, behavior: "auto" });
    document
      .getElementById("main-content")
      ?.focus({ preventScroll: true });
  }, [navigationType]);

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
    onLogout,
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
  onLogout,
}: {
  onLogout: () => void;
}) {
  const location = useLocation();
  const { id = "" } = useParams<{ id: string }>();

  return (
    <TemplateDetailRouteOwner
      key={id}
      onLogout={onLogout}
      routeState={location.state}
      templateId={id}
    />
  );
}
