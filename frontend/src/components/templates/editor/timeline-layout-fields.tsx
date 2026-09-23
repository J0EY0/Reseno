import { ChevronDown } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { FieldGroup } from "@/components/ui/field";
import { timelineSectionKinds } from "@/lib/templates";
import type { ResumeTemplateLayout } from "@/types/resume";

import { TemplateSelectField } from "./editor-fields";
import type { TemplateEditorMessages } from "./editor-messages";
import TemplateFieldsPanel from "./template-fields-panel";
import { TemplateLayoutOptionPreview } from "./template-layout-option-preview";

export function TemplateTimelineLayoutFields({
  t,
  layout,
  disabled,
  onChange,
}: {
  t: TemplateEditorMessages;
  layout: ResumeTemplateLayout;
  disabled: boolean;
  onChange: (patch: Partial<ResumeTemplateLayout>) => void;
}) {
  const options = (
    [
      ["split", t.timelineItemLayoutSplit],
      ["stacked", t.timelineItemLayoutStacked],
      ["compact", t.timelineItemLayoutCompact],
      ["inline", t.timelineItemLayoutInline],
    ] as const
  ).map(([value, label]) => ({
    value,
    label,
    preview: <TemplateLayoutOptionPreview kind="timeline" value={value} />,
  }));
  const customCount = Object.keys(layout.sectionItemLayouts).length;

  const panelId = useId();
  const [open, setOpen] = useState(customCount > 0);

  return (
    <div className="min-w-0 px-0.5">
      <TemplateSelectField
        label={t.timelineItemLayout}
        value={layout.timelineItemLayout}
        disabled={disabled}
        onChange={(value) => {
          if (!disabled) onChange({ timelineItemLayout: value });
        }}
        options={options}
      />
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="group mt-1 w-full justify-between px-0 has-[>svg]:px-0"
        aria-label={t.sectionItemLayouts}
        aria-expanded={open}
        aria-controls={panelId}
        data-state={open ? "open" : "closed"}
        onClick={() => setOpen(!open)}
      >
        <span className="text-xs font-normal text-muted-foreground">
          {t.sectionItemLayouts}
          {customCount > 0 ? ` (${customCount})` : null}
        </span>
        <ChevronDown
          data-icon="inline-end"
          aria-hidden="true"
          className="transition-transform group-data-[state=open]:rotate-180 motion-reduce:transition-none"
        />
      </Button>
      <TemplateFieldsPanel id={panelId} open={open}>
        <FieldGroup className="collapsible-content-inner gap-2.5 pb-1 pt-2">
          {timelineSectionKinds.map((kind) => (
            <TemplateSelectField
              key={kind}
              label={t.sectionTitles[kind]}
              value={layout.sectionItemLayouts[kind] ?? "inherit"}
              disabled={disabled}
              options={[
                {
                  value: "inherit",
                  label: t.sectionItemLayoutInherit,
                  preview: (
                    <TemplateLayoutOptionPreview
                      kind="timeline"
                      value={layout.timelineItemLayout}
                    />
                  ),
                },
                ...options,
              ]}
              onChange={(value) => {
                if (disabled) return;
                const sectionItemLayouts = { ...layout.sectionItemLayouts };
                if (value === "inherit") delete sectionItemLayouts[kind];
                else sectionItemLayouts[kind] = value;
                onChange({ sectionItemLayouts });
              }}
            />
          ))}
        </FieldGroup>
      </TemplateFieldsPanel>
    </div>
  );
}
