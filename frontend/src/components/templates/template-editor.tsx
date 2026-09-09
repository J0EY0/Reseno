import { CopyPlus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type { AppMessages } from "@/i18n";
import { cn } from "@/lib/utils";
import type {
  DocumentLocale,
  ResumeTemplateDefinition,
  ResumeTemplateUpdate,
} from "@/types/resume";

import { TemplateEditorTabs } from "./template-editor-tabs";
import { TemplateLocaleSelect } from "./template-locale-select";
import { TemplateMetadataDialog } from "./template-metadata-dialog";

interface TemplateEditorProps {
  t: AppMessages;
  template: ResumeTemplateDefinition;
  templateLocale: DocumentLocale;
  defaultTemplateId: string;
  isImporting: boolean;
  isCreating: boolean;
  settingDefaultTemplateId: string | null;
  onSetDefaultTemplate: (templateId: string) => void;
  onTemplateLocaleChange: (locale: DocumentLocale) => void;
  onCreateCustomTemplate: () => void;
  onUpdateTemplate: (templateId: string, patch: ResumeTemplateUpdate) => void;
}

export function TemplateEditor({
  t,
  template,
  templateLocale,
  defaultTemplateId,
  isImporting,
  isCreating,
  settingDefaultTemplateId,
  onSetDefaultTemplate,
  onTemplateLocaleChange,
  onCreateCustomTemplate,
  onUpdateTemplate,
}: TemplateEditorProps) {
  const isReadonly = Boolean(template.isBuiltIn);
  const isDefaultTemplate = template.id === defaultTemplateId;
  const isSettingDefaultTemplate = settingDefaultTemplateId === template.id;
  const defaultTemplateButtonLabel = isDefaultTemplate
    ? t.defaultTemplateLabel
    : t.setDefaultTemplate;
  const updateTemplate = (patch: ResumeTemplateUpdate) =>
    onUpdateTemplate(template.id, patch);

  return (
    <section data-slot="template-editor" className="grid min-w-0 gap-4">
      <div className="border-b border-border/40 pb-4">
        <div data-slot="template-editor-header" className="grid gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <p
                data-slot="template-editor-title"
                className="truncate text-2xl font-semibold tracking-[-0.05em] text-foreground"
              >
                {template.name}
              </p>
              {!isReadonly ? (
                <TemplateMetadataDialog
                  messages={t}
                  template={template}
                  onSave={updateTemplate}
                />
              ) : null}
              {isReadonly ? (
                <Badge
                  variant="outline"
                  className="h-7 rounded-xl border-transparent bg-muted/70 px-2.5 text-[11px] font-medium text-muted-foreground shadow-none"
                >
                  {t.templateReadonlyStatus}
                </Badge>
              ) : null}
            </div>
            <p
              data-slot="template-description"
              className="mt-1 min-h-6 max-w-[460px] text-sm leading-6 text-muted-foreground"
            >
              {template.description}
            </p>
          </div>

          <div
            data-slot="template-editor-actions"
            className="flex flex-wrap items-center gap-2"
          >
            <TemplateLocaleSelect
              disabled={settingDefaultTemplateId !== null}
              chineseLabel={t.chinesePreview}
              englishLabel={t.englishPreview}
              messages={t}
              value={templateLocale}
              onValueChange={onTemplateLocaleChange}
            />
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
              data-slot="template-default-button"
              type="button"
              size="sm"
              variant="outline"
              className={cn(
                "h-9 rounded-lg border-transparent px-3 shadow-none transition-colors disabled:opacity-100",
                isDefaultTemplate
                  ? "bg-muted/70 text-muted-foreground ring-0 hover:bg-muted/70 hover:text-muted-foreground focus-visible:ring-0 disabled:pointer-events-auto disabled:cursor-default"
                  : "bg-background/80 ring-1 ring-border/35 hover:bg-muted",
              )}
              aria-busy={isSettingDefaultTemplate || undefined}
              aria-label={defaultTemplateButtonLabel}
              onClick={() => onSetDefaultTemplate(template.id)}
              disabled={isDefaultTemplate || settingDefaultTemplateId !== null}
            >
              <span className="grid">
                <span
                  aria-hidden="true"
                  className="invisible col-start-1 row-start-1"
                >
                  {t.setDefaultTemplate}
                </span>
                <span
                  aria-hidden="true"
                  className="invisible col-start-1 row-start-1"
                >
                  {t.defaultTemplateLabel}
                </span>
                <span className="col-start-1 row-start-1">
                  {defaultTemplateButtonLabel}
                </span>
              </span>
            </Button>
          </div>
        </div>
      </div>

      <TemplateEditorTabs
        t={t}
        template={template}
        onUpdateTemplate={updateTemplate}
      />
    </section>
  );
}
