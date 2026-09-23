import { useLayoutEffect, useState } from "react";
import { useLocation, useNavigationType, useParams } from "react-router-dom";

import { ResourceRecoveryContext } from "@/components/resource-recovery-context";
import { TemplateDetailWorkspaceView } from "@/components/workspace/template-detail-workspace-view";
import { useTemplateDetailWorkspace } from "@/components/workspace/use-template-detail-workspace";
import { useWorkspacePreferences } from "@/components/workspace/workspace-preferences-context";
import {
  clearWorkspaceRouteHistoryState,
  releaseWorkspaceRouteHandoff,
} from "@/lib/workspace-route-handoff";

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

    releaseWorkspaceRouteHandoff(routeState);
    clearWorkspaceRouteHistoryState(location.key);
  }, [location.key, routeState]);

  const controller = useTemplateDetailWorkspace({
    locale,
    messages,
    onLogout,
    routeState: initialRouteState,
    templateId,
  });

  return (
    <ResourceRecoveryContext
      value={{ messages, saveAndReload: controller.saveAndReload }}
    >
      <TemplateDetailWorkspaceView
        controller={controller}
        locale={locale}
        messages={messages}
        onLocaleChange={onLocaleChange}
      />
    </ResourceRecoveryContext>
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
