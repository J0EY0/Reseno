import { LayoutTemplate, Palette, Sparkles, Type } from "lucide-react";
import { useState } from "react";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { AppMessages } from "@/i18n";
import type { ResumeTemplateDefinition } from "@/types/resume";

import { TemplateTabLabel } from "./editor/editor-fields";
import { TemplateImagesTab } from "./editor/images-tab";
import { TemplateLayoutTab } from "./editor/layout-tab";
import { TemplateTypographyTab } from "./editor/typography-tab";
import { TemplateVisualTab } from "./editor/visual-tab";

type TemplateEditorTab = "layout" | "typography" | "visual" | "images";

export function TemplateEditorTabs({
  t,
  template,
  onUpdateTemplate,
}: {
  t: AppMessages;
  template: ResumeTemplateDefinition;
  onUpdateTemplate: (patch: Partial<ResumeTemplateDefinition>) => void;
}) {
  const [editorTab, setEditorTab] = useState<TemplateEditorTab>("layout");

  return (
    <Tabs
      value={editorTab}
      onValueChange={(value) => setEditorTab(value as TemplateEditorTab)}
      className="grid gap-0"
    >
      <TabsList
        variant="line"
        className="grid w-full grid-cols-[1fr_0.82fr_0.9fr_1.28fr] gap-0 rounded-none border-0 border-b border-border/70 p-0 text-muted-foreground group-data-[orientation=horizontal]/tabs:h-12"
      >
        <TabsTrigger
          value="layout"
          className="h-12 min-w-0 items-center rounded-none border-transparent px-1.5 py-0 text-sm font-semibold after:bottom-[-1px]!"
        >
          <TemplateTabLabel icon={LayoutTemplate}>
            {t.templateLayoutTab}
          </TemplateTabLabel>
        </TabsTrigger>
        <TabsTrigger
          value="typography"
          className="h-12 min-w-0 items-center rounded-none border-transparent px-1.5 py-0 text-sm font-semibold after:bottom-[-1px]!"
        >
          <TemplateTabLabel icon={Type}>
            {t.templateTypographyTab}
          </TemplateTabLabel>
        </TabsTrigger>
        <TabsTrigger
          value="visual"
          className="h-12 min-w-0 items-center rounded-none border-transparent px-1.5 py-0 text-sm font-semibold after:bottom-[-1px]!"
        >
          <TemplateTabLabel icon={Palette}>
            {t.templateVisualTab}
          </TemplateTabLabel>
        </TabsTrigger>
        <TabsTrigger
          value="images"
          className="h-12 min-w-0 items-center rounded-none border-transparent px-1.5 py-0 text-sm font-semibold after:bottom-[-1px]!"
        >
          <TemplateTabLabel icon={Sparkles}>
            {t.templateImagesTab}
          </TemplateTabLabel>
        </TabsTrigger>
      </TabsList>

      <TemplateLayoutTab
        t={t}
        template={template}
        onUpdateTemplate={onUpdateTemplate}
      />
      <TemplateTypographyTab
        t={t}
        template={template}
        onUpdateTemplate={onUpdateTemplate}
      />
      <TemplateVisualTab
        t={t}
        template={template}
        onUpdateTemplate={onUpdateTemplate}
      />
      <TemplateImagesTab
        t={t}
        template={template}
        onUpdateTemplate={onUpdateTemplate}
      />
    </Tabs>
  );
}
