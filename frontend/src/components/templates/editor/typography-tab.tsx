import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { TabsContent } from "@/components/ui/tabs";
import type { AppMessages } from "@/i18n";
import {
  getResumeFontSizeInPoints,
  resumeFontSizeOptions,
} from "@/lib/templates";
import { cn } from "@/lib/utils";
import type {
  ResumeFontFamily,
  ResumeTemplateDefinition,
  ResumeTemplateSettings,
} from "@/types/resume";

import { TemplateSliderField } from "./editor-fields";
import { getScaleLabel } from "./editor-values";

export function TemplateTypographyTab({
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
      value="typography"
      className={cn(
        "m-0 grid gap-1 px-1 py-4",
        isReadonly && "opacity-70",
      )}
    >
      <div className="grid">
        <label className="grid min-h-[58px] grid-cols-[minmax(0,1fr)_minmax(148px,190px)] items-center gap-4 py-2 text-sm">
          <span className="min-w-0 truncate font-medium">{t.fontFamily}</span>
          <Select
            value={template.typography.fontFamily}
            disabled={isReadonly}
            onValueChange={(value) =>
              onUpdateTemplate({
                typography: {
                  ...template.typography,
                  fontFamily: value as ResumeFontFamily,
                },
              })
            }
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end" position="popper" sideOffset={4}>
              <SelectGroup>
                <SelectItem value="inter">{t.fontInter}</SelectItem>
                <SelectItem value="noto_sans_sc">{t.fontNotoSans}</SelectItem>
                <SelectItem value="serif">{t.fontSerif}</SelectItem>
                <SelectItem value="times">{t.fontTimes}</SelectItem>
                <SelectItem value="plex">{t.fontPlex}</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
        </label>

        <label className="grid min-h-[58px] grid-cols-[minmax(0,1fr)_minmax(148px,190px)] items-center gap-4 py-2 text-sm">
          <span className="min-w-0 truncate font-medium">{t.fontSize}</span>
          <Select
            value={String(template.typography.fontSize)}
            disabled={isReadonly}
            onValueChange={(value) =>
              onUpdateTemplate({
                typography: {
                  ...template.typography,
                  fontSize: Number(value),
                },
              })
            }
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end" position="popper" sideOffset={4}>
              {resumeFontSizeOptions.map((size) => (
                <SelectItem key={size} value={String(size)}>
                  {getResumeFontSizeInPoints(size)} pt
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
      </div>

      <TemplateSliderField
        label={t.nameSize}
        min={1.6}
        max={2.8}
        step={0.05}
        value={template.settings.nameScale}
        displayValue={getScaleLabel(
          template.typography.fontSize,
          template.settings.nameScale,
        )}
        onChange={(value) => updateSettings({ nameScale: value })}
        disabled={isReadonly}
      />
      <TemplateSliderField
        label={t.sectionTitleSize}
        min={0.75}
        max={1.6}
        step={0.05}
        value={template.settings.sectionTitleScale}
        displayValue={getScaleLabel(
          template.typography.fontSize,
          template.settings.sectionTitleScale,
        )}
        onChange={(value) => updateSettings({ sectionTitleScale: value })}
        disabled={isReadonly}
      />
      <TemplateSliderField
        label={t.itemTitleSize}
        min={0.85}
        max={1.4}
        step={0.05}
        value={template.settings.itemTitleScale}
        displayValue={getScaleLabel(
          template.typography.fontSize,
          template.settings.itemTitleScale,
        )}
        onChange={(value) => updateSettings({ itemTitleScale: value })}
        disabled={isReadonly}
      />
      <TemplateSliderField
        label={t.metaSize}
        min={0.75}
        max={1.15}
        step={0.05}
        value={template.settings.metaScale}
        displayValue={getScaleLabel(
          template.typography.fontSize,
          template.settings.metaScale,
        )}
        onChange={(value) => updateSettings({ metaScale: value })}
        disabled={isReadonly}
      />
      <TemplateSliderField
        label={t.bodySize}
        min={0.85}
        max={1.2}
        step={0.05}
        value={template.settings.bodyScale}
        displayValue={getScaleLabel(
          template.typography.fontSize,
          template.settings.bodyScale,
        )}
        onChange={(value) => updateSettings({ bodyScale: value })}
        disabled={isReadonly}
      />
    </TabsContent>
  );
}
