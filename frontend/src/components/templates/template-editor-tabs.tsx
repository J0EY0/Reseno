import { ImagePlus, Palette, PanelsTopLeft, Type } from "lucide-react";
import {
  lazy,
  Suspense,
  useEffect,
  useState,
  type ComponentProps,
  type ComponentType,
} from "react";

import { ResourceErrorBoundary } from "@/components/resource-error-boundary";
import { Skeleton } from "@/components/ui/skeleton";
import type { Locale } from "@/i18n";
import type {
  ResumeTemplateDefinition,
  ResumeTemplateUpdate,
} from "@/types/resume";

import type { TemplateEditorMessages } from "./editor/editor-messages";

import { TemplateLayoutTab } from "./editor/layout-tab";
import { TemplateTypographyTab } from "./editor/typography-tab";
import {
  TemplateStyleTabs,
  TemplateStyleTabsContent,
  TemplateStyleTabsList,
  TemplateStyleTabsTrigger,
} from "./template-style-tabs";

function createTabLoader<Props>(
  loader: () => Promise<{ default: ComponentType<Props> }>,
) {
  let loaded: ComponentType<Props> | undefined;
  let request: ReturnType<typeof loader>;
  const preload = () =>
    (request ||= loader().then((module) => {
      loaded = module.default;
      return module;
    }));
  const LazyTab = lazy(preload);
  return { preload, getComponent: () => loaded ?? LazyTab };
}

const imagesTab = createTabLoader<
  ComponentProps<typeof import("./editor/images-tab").TemplateImagesTab>
>(() =>
  import("./editor/images-tab").then((module) => ({
    default: module.TemplateImagesTab,
  })),
);
const visualTab = createTabLoader<
  ComponentProps<typeof import("./editor/visual-tab").TemplateVisualTab>
>(() =>
  import("./editor/visual-tab").then((module) => ({
    default: module.TemplateVisualTab,
  })),
);

export function TemplateEditorTabs({
  t,
  locale,
  template,
  onUpdateTemplate,
}: {
  t: TemplateEditorMessages;
  locale: Locale;
  template: ResumeTemplateDefinition;
  onUpdateTemplate: (patch: ResumeTemplateUpdate) => void;
}) {
  const [ImagesTab, setImagesTab] =
    useState<ReturnType<typeof imagesTab.getComponent>>();
  const [VisualTab, setVisualTab] =
    useState<ReturnType<typeof visualTab.getComponent>>();

  useEffect(() => {
    void visualTab.preload().catch(() => undefined);
    void imagesTab.preload().catch(() => undefined);
  }, []);

  return (
    <TemplateStyleTabs
      className="min-w-0"
      defaultValue="layout"
      onValueChange={(value) => {
        if (value === "images" && !ImagesTab)
          setImagesTab(imagesTab.getComponent);
        if (value === "visual" && !VisualTab)
          setVisualTab(visualTab.getComponent);
      }}
    >
      <TemplateStyleTabsList aria-label={t.resumeTemplates}>
        <TemplateStyleTabsTrigger value="layout">
          <PanelsTopLeft aria-hidden="true" />
          {t.templateLayoutTab}
        </TemplateStyleTabsTrigger>
        <TemplateStyleTabsTrigger value="typography">
          <Type aria-hidden="true" />
          {t.templateTypographyTab}
        </TemplateStyleTabsTrigger>
        <TemplateStyleTabsTrigger value="visual">
          <Palette aria-hidden="true" />
          {t.templateVisualTab}
        </TemplateStyleTabsTrigger>
        <TemplateStyleTabsTrigger value="images">
          <ImagePlus aria-hidden="true" />
          {t.templateImagesTab}
        </TemplateStyleTabsTrigger>
      </TemplateStyleTabsList>

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
      {VisualTab ? (
        <TemplateStyleTabsContent
          value="visual"
          animate
          keepMounted
          className="template-control-stack py-5"
        >
          <ResourceErrorBoundary>
            <Suspense
              fallback={
                <div aria-busy="true" className="grid gap-3">
                  <Skeleton className="h-20 w-full" />
                  <Skeleton className="h-9 w-full" />
                </div>
              }
            >
              <VisualTab
                t={t}
                template={template}
                onUpdateTemplate={onUpdateTemplate}
              />
            </Suspense>
          </ResourceErrorBoundary>
        </TemplateStyleTabsContent>
      ) : null}
      {ImagesTab ? (
        <TemplateStyleTabsContent
          value="images"
          animate
          keepMounted
          className="py-5"
        >
          <ResourceErrorBoundary>
            <Suspense
              fallback={
                <div aria-busy="true" className="grid gap-3">
                  <Skeleton className="h-9 w-full" />
                  <Skeleton className="h-20 w-full" />
                </div>
              }
            >
              <ImagesTab
                t={t}
                locale={locale}
                template={template}
                onUpdateTemplate={onUpdateTemplate}
              />
            </Suspense>
          </ResourceErrorBoundary>
        </TemplateStyleTabsContent>
      ) : null}
    </TemplateStyleTabs>
  );
}
