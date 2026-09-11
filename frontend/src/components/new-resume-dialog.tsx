import { CopyPlus } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AppMessages } from "@/i18n";
import type {
  DocumentLocale,
  ResumeTemplateDefinition,
  ResumeTemplateId,
} from "@/types/resume";

export function NewResumeDialog({
  disabled,
  isCreating,
  messages,
  templates,
  defaultTemplateId,
  onCreateResume,
}: {
  disabled: boolean;
  isCreating: boolean;
  messages: AppMessages;
  templates: ResumeTemplateDefinition[];
  defaultTemplateId: ResumeTemplateId;
  onCreateResume: (
    documentLocale: DocumentLocale,
    templateId: ResumeTemplateId,
  ) => void;
}) {
  const [documentLocale, setDocumentLocale] = useState<DocumentLocale | null>(
    null,
  );
  const [templateId, setTemplateId] = useState(defaultTemplateId);

  return (
    <Dialog
      onOpenChange={() => {
        setDocumentLocale(null);
        setTemplateId(defaultTemplateId);
      }}
    >
      <DialogTrigger asChild>
        <Button
          type="button"
          disabled={disabled}
          aria-label={isCreating ? messages.creating : messages.newResume}
          aria-busy={isCreating || undefined}
        >
          <CopyPlus data-icon="inline-start" />
          {messages.newResume}
        </Button>
      </DialogTrigger>
      <DialogContent
        closeLabel={messages.close}
        aria-describedby={undefined}
        className="new-resume-dialog"
      >
        <DialogTitle>{messages.createResume}</DialogTitle>
        <form
          className="grid gap-6"
          onSubmit={(event) => {
            event.preventDefault();
            if (documentLocale) {
              onCreateResume(documentLocale, templateId);
            }
          }}
        >
          <FieldGroup className="grid grid-cols-1 gap-x-3 gap-y-6 sm:grid-cols-[auto_minmax(0,1fr)]">
            <Field className="col-span-full grid grid-cols-subgrid items-center gap-3">
              <FieldLabel htmlFor="new-resume-language">
                {messages.resumeLanguage}
              </FieldLabel>
              <Select
                value={documentLocale ?? ""}
                onValueChange={(value) =>
                  setDocumentLocale(value as DocumentLocale)
                }
              >
                <SelectTrigger id="new-resume-language" className="w-full">
                  <SelectValue placeholder={messages.selectResumeLanguage} />
                </SelectTrigger>
                <SelectContent align="end" position="popper" sideOffset={4}>
                  <SelectGroup>
                    <SelectItem value="zh">
                      {messages.languageChinese}
                    </SelectItem>
                    <SelectItem value="en">
                      {messages.languageEnglish}
                    </SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field className="col-span-full grid grid-cols-subgrid items-center gap-3">
              <FieldLabel htmlFor="new-resume-template">
                {messages.template}
              </FieldLabel>
              <Select value={templateId} onValueChange={setTemplateId}>
                <SelectTrigger id="new-resume-template" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="end" position="popper" sideOffset={4}>
                  <SelectGroup>
                    {templates.map(({ id, name }) => (
                      <SelectItem key={id} value={id}>
                        {name}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
          </FieldGroup>
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                {messages.cancel}
              </Button>
            </DialogClose>
            <Button
              type="submit"
              disabled={!documentLocale}
              aria-disabled={isCreating || undefined}
            >
              {messages.createResume}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
