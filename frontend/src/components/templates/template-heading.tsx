import { Badge } from "@/components/ui/badge";
import type {
  ResumeTemplateDefinition,
  ResumeTemplateUpdate,
} from "@/types/resume";

import { TemplateMetadataDialog } from "./template-metadata-dialog";
import type { TemplateEditorMessages } from "./editor/editor-messages";

export function TemplateHeading({
  messages,
  template,
  onUpdateTemplate,
}: {
  messages: TemplateEditorMessages;
  template: ResumeTemplateDefinition;
  onUpdateTemplate: (templateId: string, patch: ResumeTemplateUpdate) => void;
}) {
  return (
    <div className="flex min-w-0 flex-1 items-center gap-4">
      <div className="flex min-w-0 items-center gap-2 sm:gap-3">
        <h1
          data-slot="template-editor-title"
          className="min-w-0 truncate text-sm font-semibold tracking-tight sm:text-lg"
          title={template.name}
        >
          {template.name}
        </h1>
        {template.isBuiltIn ? (
          <Badge
            variant="secondary"
            className="rounded-md px-1.5 text-[11px]"
            title={messages.templateReadonlyStatus}
          >
            {messages.templateReadonlyLabel}
          </Badge>
        ) : (
          <TemplateMetadataDialog
            messages={messages}
            template={template}
            onSave={(patch) => onUpdateTemplate(template.id, patch)}
          />
        )}
      </div>
      {template.description ? (
        <p
          data-slot="template-description"
          className="hidden min-w-0 flex-1 truncate border-l pl-4 text-xs leading-5 text-muted-foreground xl:block"
          title={template.description}
        >
          {template.description}
        </p>
      ) : null}
    </div>
  );
}
