import { useMemo } from "react";

import type { AppMessages, Locale } from "@/i18n";
import type {
  ResumeTemplateDefinition,
  ResumeTemplateUpdate,
} from "@/types/resume";

import { getTemplateEditorMessages } from "./editor/editor-messages";
import { TemplateActions } from "./template-actions";
import { TemplateEditorTabs } from "./template-editor-tabs";

import "./template-editor.css";

interface TemplateEditorProps {
  t: AppMessages;
  locale: Locale;
  template: ResumeTemplateDefinition;
  defaultTemplateId: string;
  isCreating: boolean;
  settingDefaultTemplateId: string | null;
  onCreateCustomTemplate: () => void;
  onSetDefaultTemplate: (templateId: string) => void;
  onUpdateTemplate: (templateId: string, patch: ResumeTemplateUpdate) => void;
}

export function TemplateEditor({
  t,
  locale,
  template,
  defaultTemplateId,
  isCreating,
  settingDefaultTemplateId,
  onCreateCustomTemplate,
  onSetDefaultTemplate,
  onUpdateTemplate,
}: TemplateEditorProps) {
  const editorMessages = useMemo(
    () => getTemplateEditorMessages(locale, t),
    [locale, t],
  );
  const updateTemplate = (patch: ResumeTemplateUpdate) =>
    onUpdateTemplate(template.id, patch);
  return (
    <section
      data-slot="template-editor"
      lang={locale}
      className="@container/template-editor grid min-w-0 gap-3.5"
    >
      <header
        data-slot="template-editor-header"
        className="flex min-h-8 flex-wrap items-center justify-between gap-2"
      >
        <h2 className="shrink-0 text-sm font-semibold">
          {editorMessages.templateGlobalStyles}
        </h2>
        <TemplateActions
          messages={editorMessages}
          template={template}
          defaultTemplateId={defaultTemplateId}
          isCreating={isCreating}
          settingDefaultTemplateId={settingDefaultTemplateId}
          onCreateCustomTemplate={onCreateCustomTemplate}
          onSetDefaultTemplate={onSetDefaultTemplate}
        />
      </header>
      <TemplateEditorTabs
        t={editorMessages}
        locale={locale}
        template={template}
        onUpdateTemplate={updateTemplate}
      />
    </section>
  );
}
