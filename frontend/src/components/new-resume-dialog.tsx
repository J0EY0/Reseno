import { CopyPlus } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
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
import { Spinner } from "@/components/ui/spinner";
import type { AppMessages } from "@/i18n";
import type { DocumentLocale } from "@/types/resume";

export function NewResumeDialog({
  disabled,
  isCreating,
  messages,
  onCreateResume,
}: {
  disabled: boolean;
  isCreating: boolean;
  messages: AppMessages;
  onCreateResume: (documentLocale: DocumentLocale) => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [documentLocale, setDocumentLocale] =
    useState<DocumentLocale | null>(null);

  function handleOpenChange(open: boolean) {
    setIsOpen(open);
    if (!open) {
      setDocumentLocale(null);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (documentLocale) {
      onCreateResume(documentLocale);
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button
          type="button"
          disabled={disabled}
          aria-busy={isCreating || undefined}
        >
          {isCreating ? (
            <Spinner data-icon="inline-start" aria-label={messages.creating} />
          ) : (
            <CopyPlus data-icon="inline-start" />
          )}
          {isCreating ? messages.creating : messages.newResume}
        </Button>
      </DialogTrigger>
      <DialogContent closeLabel={messages.close}>
        <DialogHeader>
          <DialogTitle>{messages.createResume}</DialogTitle>
          <DialogDescription>
            {messages.newResumeDialogDescription}
          </DialogDescription>
        </DialogHeader>
        <form className="flex flex-col gap-6" onSubmit={handleSubmit}>
          <FieldGroup>
            <Field>
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
                <SelectContent>
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
          </FieldGroup>
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                {messages.cancel}
              </Button>
            </DialogClose>
            <Button type="submit" disabled={!documentLocale || isCreating}>
              {isCreating ? (
                <Spinner
                  data-icon="inline-start"
                  aria-label={messages.creating}
                />
              ) : null}
              {isCreating ? messages.creating : messages.createResume}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
