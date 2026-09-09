import { TabsContent } from "@/components/ui/tabs";
import type { AppMessages } from "@/i18n";
import { cn } from "@/lib/utils";
import type {
  ResumeTemplateDefinition,
  ResumeTemplateSettings,
} from "@/types/resume";

import { TemplateColorField } from "./editor-fields";

export function TemplateVisualTab({
  t,
  template,
  onUpdateTemplate,
}: {
  t: AppMessages;
  template: ResumeTemplateDefinition;
  onUpdateTemplate: (patch: Partial<ResumeTemplateDefinition>) => void;
}) {
  const isReadonly = Boolean(template.isBuiltIn);

  function updateSettings(patch: Partial<ResumeTemplateSettings>) {
    if (isReadonly) {
      return;
    }

    onUpdateTemplate({
      settings: {
        ...template.settings,
        ...patch,
      },
    });
  }

  return (
    <TabsContent
      value="visual"
      className={cn("m-0 grid gap-1 px-1 py-4", isReadonly && "opacity-70")}
    >
      <TemplateColorField
        label={t.pageBackground}
        value={template.settings.pageBackground}
        onChange={(value) => updateSettings({ pageBackground: value })}
        disabled={isReadonly}
      />
      <TemplateColorField
        label={t.surfaceColor}
        value={template.settings.surfaceColor}
        onChange={(value) => updateSettings({ surfaceColor: value })}
        disabled={isReadonly}
      />
      <TemplateColorField
        label={t.headingColor}
        value={template.settings.headingColor}
        onChange={(value) => updateSettings({ headingColor: value })}
        disabled={isReadonly}
      />
      <TemplateColorField
        label={t.bodyColor}
        value={template.settings.bodyColor}
        onChange={(value) => updateSettings({ bodyColor: value })}
        disabled={isReadonly}
      />
      <TemplateColorField
        label={t.mutedColor}
        value={template.settings.mutedColor}
        onChange={(value) => updateSettings({ mutedColor: value })}
        disabled={isReadonly}
      />
      <TemplateColorField
        label={t.dividerColor}
        value={template.settings.dividerColor}
        onChange={(value) => updateSettings({ dividerColor: value })}
        disabled={isReadonly}
      />
    </TabsContent>
  );
}
