import { LayoutTemplate, Palette, Sparkles, Type } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";

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
  const tabsListRef = useRef<HTMLDivElement>(null);
  const indicatorRef = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    const list = tabsListRef.current;
    const indicator = indicatorRef.current;

    if (!list || !indicator) return;

    let animationFrame: number | null = null;

    const syncIndicator = () => {
      animationFrame = null;

      const activeTrigger = list.querySelector<HTMLElement>(
        '[data-slot="tabs-trigger"][data-state="active"]',
      );

      if (!activeTrigger) return;

      const listRect = list.getBoundingClientRect();
      const activeRect = activeTrigger.getBoundingClientRect();
      const offset = activeRect.left - listRect.left;
      const width = activeRect.width;
      const nextWidth = `${width}px`;
      const nextTransform = `translate3d(${offset}px, 0, 0)`;

      if (indicator.style.width !== nextWidth) {
        indicator.style.width = `${width}px`;
      }
      if (indicator.style.transform !== nextTransform) {
        indicator.style.transform = `translate3d(${offset}px, 0, 0)`;
      }
      indicator.dataset.ready = "true";
    };

    const scheduleIndicatorSync = () => {
      if (animationFrame !== null) return;
      animationFrame = requestAnimationFrame(syncIndicator);
    };

    syncIndicator();

    const resizeObserver = new ResizeObserver(scheduleIndicatorSync);
    resizeObserver.observe(list);
    list
      .querySelectorAll<HTMLElement>('[data-slot="tabs-trigger"]')
      .forEach((trigger) => resizeObserver.observe(trigger));

    return () => {
      resizeObserver.disconnect();
      if (animationFrame !== null) cancelAnimationFrame(animationFrame);
    };
  }, [
    editorTab,
    t.templateImagesTab,
    t.templateLayoutTab,
    t.templateTypographyTab,
    t.templateVisualTab,
  ]);

  return (
    <Tabs
      value={editorTab}
      onValueChange={(value) => setEditorTab(value as TemplateEditorTab)}
      className="grid gap-0"
    >
      <TabsList ref={tabsListRef} className="relative max-w-full">
        <span
          ref={indicatorRef}
          aria-hidden="true"
          data-ready="false"
          className="pointer-events-none absolute inset-y-[3.5px] left-0 rounded-md border border-transparent bg-background opacity-0 shadow-sm transition-[transform,width] duration-200 ease-out data-[ready=true]:opacity-100 motion-reduce:transition-none dark:border-input dark:bg-input/30"
        />
        <TabsTrigger
          value="layout"
          className="min-w-0 flex-[0_1_auto] data-[state=active]:border-transparent! data-[state=active]:bg-transparent! data-[state=active]:shadow-none!"
        >
          <TemplateTabLabel icon={LayoutTemplate}>
            {t.templateLayoutTab}
          </TemplateTabLabel>
        </TabsTrigger>
        <TabsTrigger
          value="typography"
          className="min-w-0 flex-[0_1_auto] data-[state=active]:border-transparent! data-[state=active]:bg-transparent! data-[state=active]:shadow-none!"
        >
          <TemplateTabLabel icon={Type}>
            {t.templateTypographyTab}
          </TemplateTabLabel>
        </TabsTrigger>
        <TabsTrigger
          value="visual"
          className="min-w-0 flex-[0_1_auto] data-[state=active]:border-transparent! data-[state=active]:bg-transparent! data-[state=active]:shadow-none!"
        >
          <TemplateTabLabel icon={Palette}>
            {t.templateVisualTab}
          </TemplateTabLabel>
        </TabsTrigger>
        <TabsTrigger
          value="images"
          className="min-w-0 flex-[0_1_auto] data-[state=active]:border-transparent! data-[state=active]:bg-transparent! data-[state=active]:shadow-none!"
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
