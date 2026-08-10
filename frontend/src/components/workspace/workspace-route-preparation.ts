import { fetchWorkspaceRouteData } from "@/lib/workspace-api";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import type { PreparedWorkspaceRoute } from "@/lib/workspace-route-memory";
import type { WorkspaceView } from "@/types/resume";

function loadWorkspaceRouteModule(view: WorkspaceView) {
  switch (view) {
    case "models":
      return import("@/components/workspace/models-workspace-page");
    case "settings":
      return import("@/components/workspace/settings-workspace-page");
    case "templates":
      return import(
        "@/components/workspace/template-gallery-workspace-page"
      );
    case "trash":
      return import("@/components/workspace/trash-workspace-page");
    case "resume":
      return import("@/components/workspace/resume-gallery-workspace-page");
  }
}

async function loadWorkspaceRouteData(
  view: WorkspaceView,
  persistence: WorkspacePreferencesPersistence,
): Promise<PreparedWorkspaceRoute> {
  await persistence.flush();

  switch (view) {
    case "resume": {
      const source = await fetchWorkspaceRouteData("resume-gallery", {
        notifyOnError: false,
      });
      return { data: source.data, view };
    }
    case "templates": {
      const source = await fetchWorkspaceRouteData("template-gallery", {
        notifyOnError: false,
      });
      return { data: source.data, view };
    }
    case "trash": {
      const source = await fetchWorkspaceRouteData("trash", {
        notifyOnError: false,
      });
      return { data: source.data, view };
    }
    case "models": {
      const source = await fetchWorkspaceRouteData("models", {
        notifyOnError: false,
      });
      return { data: source.data, view };
    }
    case "settings": {
      const source = await fetchWorkspaceRouteData("settings", {
        notifyOnError: false,
      });
      return { data: source.data, view };
    }
  }
}

export async function prepareWorkspaceRoute<View extends WorkspaceView>(
  view: View,
  persistence: WorkspacePreferencesPersistence,
): Promise<PreparedWorkspaceRoute<View>> {
  const [, prepared] = await Promise.all([
    loadWorkspaceRouteModule(view),
    loadWorkspaceRouteData(view, persistence),
  ]);

  return prepared as PreparedWorkspaceRoute<View>;
}
