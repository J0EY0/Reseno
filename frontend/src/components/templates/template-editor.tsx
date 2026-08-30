import { CopyPlus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import type { AppMessages } from "@/i18n";
import { cn } from "@/lib/utils";
import type { ResumeTemplateDefinition } from "@/types/resume";

import { TemplateEditorPanel } from "./editor/editor-fields";
import { TemplateEditorTabs } from "./template-editor-tabs";

interface TemplateEditorProps {
  t: AppMessages;
  template: ResumeTemplateDefinition;
  defaultTemplateId: string;
  isImporting: boolean;
  isCreating: boolean;
  settingDefaultTemplateId: string | null;
  onSetDefaultTemplate: (templateId: string) => void;
  onCreateCustomTemplate: () => void;
  onUpdateTemplate: (
    templateId: string,
    patch: Partial<ResumeTemplateDefinition>,
  ) => void;
}

export function TemplateEditor({
  t,
  template,
  defaultTemplateId,
  isImporting,
  isCreating,
  settingDefaultTemplateId,
  onSetDefaultTemplate,
  onCreateCustomTemplate,
  onUpdateTemplate,
}: TemplateEditorProps) {
  const isReadonly = Boolean(template.isBuiltIn);
  const updateTemplate = (patch: Partial<ResumeTemplateDefinition>) =>
    onUpdateTemplate(template.id, patch);

  return (
    <div className="grid gap-4">
      <Card className="overflow-hidden rounded-(--radius-workspace) border border-border/80 bg-card shadow-none">
        <CardContent className="template-editor-scroll p-0">
          <div className="sticky top-0 z-20 border-b border-border/40 bg-card/95 px-5 py-4 backdrop-blur">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="truncate text-2xl font-semibold tracking-[-0.05em] text-foreground">
                    {template.name}
                  </p>
                  <Badge
                    variant="outline"
                    className="h-7 rounded-xl border-transparent bg-muted/70 px-2.5 text-[11px] font-medium text-muted-foreground shadow-none"
                  >
                    {isReadonly
                      ? t.templateReadonlyStatus
                      : t.templateEditableStatus}
                  </Badge>
                </div>
                <p className="mt-1 max-w-[460px] text-sm leading-6 text-muted-foreground">
                  {template.description || t.templateDescriptionFallback}
                </p>
              </div>

              <div className="flex shrink-0 flex-wrap items-center gap-2">
                {isReadonly ? (
                  <Button
                    type="button"
                    size="sm"
                    className="h-9 rounded-lg px-3 shadow-none"
                    disabled={isImporting || isCreating}
                    onClick={onCreateCustomTemplate}
                  >
                    {isCreating ? (
                      <Spinner
                        data-icon="inline-start"
                        aria-label={t.createEditableCopy}
                      />
                    ) : (
                      <CopyPlus data-icon="inline-start" />
                    )}
                    {t.createEditableCopy}
                  </Button>
                ) : null}
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className={cn(
                    "h-9 rounded-lg border-transparent px-3 shadow-none",
                    template.id === defaultTemplateId
                      ? "bg-muted/70 text-muted-foreground ring-0 hover:bg-muted/70 hover:text-muted-foreground focus-visible:ring-0 disabled:pointer-events-auto disabled:cursor-default disabled:opacity-100"
                      : "bg-background/80 ring-1 ring-border/35 hover:bg-muted",
                  )}
                  onClick={() => onSetDefaultTemplate(template.id)}
                  disabled={
                    template.id === defaultTemplateId ||
                    settingDefaultTemplateId !== null
                  }
                >
                  {settingDefaultTemplateId === template.id ? (
                    <Spinner
                      data-icon="inline-start"
                      aria-label={t.setDefaultTemplate}
                    />
                  ) : null}
                  {template.id === defaultTemplateId
                    ? t.defaultTemplateLabel
                    : t.setDefaultTemplate}
                </Button>
              </div>
            </div>
          </div>

          <div className="grid gap-4 p-5">
            <div className="grid gap-3">
              {!isReadonly ? (
                <TemplateEditorPanel
                  title={t.templateInfoPanel}
                  defaultOpen={false}
                  badge={
                    <Badge
                      variant="outline"
                      className="h-7 rounded-xl border-transparent bg-background/80 px-2.5 text-[11px] font-medium text-muted-foreground shadow-none ring-1 ring-border/35"
                    >
                      {t.customTemplate}
                    </Badge>
                  }
                >
                  <div className="grid gap-4">
                    <label className="grid gap-2 text-sm">
                      <span className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                        {t.templateName}
                      </span>
                      <Input
                        className="h-11 rounded-xl bg-background/80 shadow-none"
                        value={template.name}
                        onChange={(event) =>
                          updateTemplate({ name: event.target.value })
                        }
                      />
                    </label>

                    <label className="grid gap-2 text-sm">
                      <span className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                        {t.templateDescription}
                      </span>
                      <Textarea
                        className="rounded-xl bg-background/80 shadow-none"
                        rows={3}
                        value={template.description}
                        onChange={(event) =>
                          updateTemplate({ description: event.target.value })
                        }
                      />
                    </label>
                  </div>
                </TemplateEditorPanel>
              ) : null}

              <TemplateEditorTabs
                t={t}
                template={template}
                onUpdateTemplate={updateTemplate}
              />
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
