import { useLocation, useParams } from "react-router-dom";

import { TemplateDetailWorkspaceView } from "@/components/workspace/template-detail-workspace-view";
import { useTemplateDetailWorkspace } from "@/components/workspace/use-template-detail-workspace";
import type { AppMessages, Locale } from "@/i18n";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";

/** Binds the route parameter and handoff state to the template workspace. */
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
  const controller = useTemplateDetailWorkspace({
    locale,
    messages,
    onLocaleChange,
    onLogout,
    persistence,
    routeState: location.state,
    templateId: id,
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
