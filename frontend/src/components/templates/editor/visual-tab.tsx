import { FieldGroup } from "@/components/ui/field";
import { Separator } from "@/components/ui/separator";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type {
  ResumeTemplateDefinition,
  ResumeTemplateSettings,
} from "@/types/resume";

import type { TemplateEditorMessages } from "./editor-messages";
import { TemplateColorField, TemplateControlSection } from "./editor-fields";

const colorFields = [
  "pageBackground",
  "surfaceColor",
  "headingColor",
  "bodyColor",
  "mutedColor",
  "dividerColor",
] as const;
const palettes = {
  monochrome: {
    pageBackground: "#ffffff",
    surfaceColor: "#f8fafc",
    headingColor: "#27272a",
    bodyColor: "#27272a",
    mutedColor: "#71717a",
    dividerColor: "#d4d4d8",
  },
  blue: {
    pageBackground: "#ffffff",
    surfaceColor: "#f1f5fa",
    headingColor: "#334c70",
    bodyColor: "#27272a",
    mutedColor: "#7489a5",
    dividerColor: "#d9e2ee",
  },
  green: {
    pageBackground: "#ffffff",
    surfaceColor: "#f0f5f2",
    headingColor: "#36594d",
    bodyColor: "#27272a",
    mutedColor: "#83998f",
    dividerColor: "#d9e5de",
  },
} as const;

export function TemplateVisualTab({
  t,
  template,
  onUpdateTemplate,
}: {
  t: TemplateEditorMessages;
  template: ResumeTemplateDefinition;
  onUpdateTemplate: (patch: Partial<ResumeTemplateDefinition>) => void;
}) {
  const isReadonly = Boolean(template.isBuiltIn);
  const selectedPalette =
    Object.entries(palettes).find(([, colors]) =>
      colorFields.every(
        (key) => colors[key] === template.settings[key].toLowerCase(),
      ),
    )?.[0] ?? "";

  function updateSettings(patch: Partial<ResumeTemplateSettings>) {
    if (!isReadonly)
      onUpdateTemplate({ settings: { ...template.settings, ...patch } });
  }

  return (
    <>
      <TemplateControlSection title={t.templateColorPresets}>
        <ToggleGroup
          type="single"
          value={selectedPalette}
          disabled={isReadonly}
          aria-label={t.templateColorPresets}
          spacing={2}
          className="grid w-full grid-cols-3"
          onValueChange={(value) => {
            if (value) updateSettings(palettes[value as keyof typeof palettes]);
          }}
        >
          {(
            [
              ["monochrome", t.templatePaletteMonochrome],
              ["blue", t.templatePaletteBlue],
              ["green", t.templatePaletteGreen],
            ] as const
          ).map(([key, label]) => (
            <ToggleGroupItem
              key={key}
              value={key}
              variant="outline"
              className="template-palette h-auto min-w-0 flex-col gap-2 px-2 py-2.5 text-xs disabled:opacity-100"
            >
              <span
                className="flex h-4 w-full overflow-hidden rounded-sm"
                aria-hidden="true"
              >
                {[
                  palettes[key].headingColor,
                  palettes[key].mutedColor,
                  palettes[key].dividerColor,
                ].map((color) => (
                  <span
                    key={color}
                    className="flex-1"
                    style={{ backgroundColor: color }}
                  />
                ))}
              </span>
              <span className="max-w-full whitespace-normal text-center">
                {label}
              </span>
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </TemplateControlSection>
      <Separator />
      <TemplateControlSection title={t.templateCustomColors}>
        <FieldGroup className="grid grid-cols-2 gap-x-3 gap-y-3">
          {colorFields.map((key) => (
            <TemplateColorField
              key={key}
              label={t[key]}
              value={template.settings[key]}
              onChange={(value) => updateSettings({ [key]: value })}
              disabled={isReadonly}
            />
          ))}
        </FieldGroup>
      </TemplateControlSection>
    </>
  );
}
