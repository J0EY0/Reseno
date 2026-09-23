import { Bookmark, CopyPlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import type { ResumeTemplateDefinition } from "@/types/resume";

import type { TemplateEditorMessages } from "./editor/editor-messages";

export function TemplateActions({
  messages,
  template,
  defaultTemplateId,
  isCreating,
  settingDefaultTemplateId,
  onSetDefaultTemplate,
  onCreateCustomTemplate,
}: {
  messages: TemplateEditorMessages;
  template: ResumeTemplateDefinition;
  defaultTemplateId: string;
  isCreating: boolean;
  settingDefaultTemplateId: string | null;
  onSetDefaultTemplate: (templateId: string) => void;
  onCreateCustomTemplate: () => void;
}) {
  const isDefault = template.id === defaultTemplateId;
  const isSettingDefault = template.id === settingDefaultTemplateId;
  const defaultLabel = isDefault
    ? messages.defaultTemplateLabel
    : messages.setDefaultTemplate;

  return (
    <div
      data-slot="template-editor-actions"
      className="flex shrink-0 items-center gap-1.5"
    >
      {template.isBuiltIn ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="text-xs shadow-none"
          aria-label={messages.createEditableCopy}
          title={messages.createEditableCopy}
          disabled={isCreating}
          onClick={onCreateCustomTemplate}
        >
          {isCreating ? (
            <Spinner data-icon="inline-start" />
          ) : (
            <CopyPlus data-icon="inline-start" />
          )}
          {messages.createEditableCopy}
        </Button>
      ) : null}
      <Button
        data-slot="template-default-button"
        type="button"
        variant={isDefault ? "secondary" : "outline"}
        size="sm"
        className={cn(
          "border px-2.5 text-xs shadow-none transition-colors duration-200 ease-out motion-reduce:transition-none disabled:opacity-100",
          isDefault && "border-transparent text-muted-foreground",
        )}
        aria-label={defaultLabel}
        title={defaultLabel}
        aria-busy={isSettingDefault || undefined}
        disabled={isDefault || settingDefaultTemplateId !== null}
        onClick={() => onSetDefaultTemplate(template.id)}
      >
        <span aria-hidden="true" className="grid">
          <span
            data-slot="template-default-action"
            className={cn(
              "col-start-1 row-start-1 inline-flex items-center justify-center gap-1.5 transition-opacity duration-150 ease-out motion-reduce:transition-none",
              isDefault ? "opacity-0" : "opacity-100",
            )}
          >
            <span className="inline-flex size-4 items-center justify-center">
              {isDefault ? null : isSettingDefault ? (
                <Spinner className="motion-reduce:animate-none" />
              ) : (
                <Bookmark />
              )}
            </span>
            {messages.setDefaultTemplate}
          </span>
          <span
            data-slot="template-default-status"
            className={cn(
              "col-start-1 row-start-1 inline-flex items-center justify-center transition-opacity duration-150 ease-out motion-reduce:transition-none",
              isDefault ? "opacity-100" : "opacity-0",
            )}
          >
            {messages.defaultTemplateLabel}
          </span>
        </span>
      </Button>
    </div>
  );
}
