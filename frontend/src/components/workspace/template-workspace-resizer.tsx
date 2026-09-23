import type { ComponentProps } from "react";

import WorkspacePanelResizer from "./workspace-panel-resizer";
import type { Locale } from "@/i18n";
import workspaceResizeMessages from "@/i18n/workspace-resize.json";

export default function TemplateWorkspaceResizer({
  locale,
  ...props
}: Omit<ComponentProps<typeof WorkspacePanelResizer>, "direction" | "label"> & {
  locale: Locale;
}) {
  return (
    <WorkspacePanelResizer
      {...props}
      direction="right"
      label={workspaceResizeMessages[locale].workspaceResizeEditor}
    />
  );
}
