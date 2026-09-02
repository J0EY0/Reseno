import { Pencil } from "lucide-react";
import { useId, useState, type FormEvent } from "react";

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
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { AppMessages } from "@/i18n";
import type { ResumeTemplateDefinition } from "@/types/resume";

export function TemplateMetadataDialog({
  messages,
  template,
  onSave,
}: {
  messages: AppMessages;
  template: Pick<ResumeTemplateDefinition, "name" | "description">;
  onSave: (
    patch: Pick<ResumeTemplateDefinition, "name" | "description">,
  ) => void;
}) {
  const nameInputId = useId();
  const descriptionInputId = useId();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(template.name);
  const [description, setDescription] = useState(template.description);

  function handleOpenChange(nextOpen: boolean) {
    if (nextOpen) {
      setName(template.name);
      setDescription(template.description);
    }
    setOpen(nextOpen);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) {
      return;
    }

    onSave({ name: trimmedName, description });
    setOpen(false);
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button
          data-template-metadata-trigger="true"
          type="button"
          variant="ghost"
          size="icon-sm"
          title={messages.editTemplateInfo}
          aria-label={messages.editTemplateInfo}
        >
          <Pencil
            aria-hidden="true"
            className="size-3.5 text-muted-foreground"
          />
        </Button>
      </DialogTrigger>
      <DialogContent
        data-template-metadata-dialog="true"
        closeLabel={messages.close}
        className="w-[min(460px,calc(100vw-2rem))]"
      >
        <form className="grid gap-4" onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>{messages.editTemplateInfo}</DialogTitle>
            <DialogDescription>
              {messages.editTemplateInfoDescription}
            </DialogDescription>
          </DialogHeader>

          <FieldGroup className="gap-4">
            <Field>
              <FieldLabel htmlFor={nameInputId}>
                {messages.templateName}
              </FieldLabel>
              <Input
                id={nameInputId}
                name="templateName"
                value={name}
                autoComplete="off"
                autoFocus
                required
                onChange={(event) => setName(event.target.value)}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor={descriptionInputId}>
                {messages.templateDescription}
              </FieldLabel>
              <Textarea
                id={descriptionInputId}
                name="templateDescription"
                value={description}
                autoComplete="off"
                rows={4}
                placeholder={messages.templateDescriptionFallback}
                onChange={(event) => setDescription(event.target.value)}
              />
            </Field>
          </FieldGroup>

          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                {messages.cancel}
              </Button>
            </DialogClose>
            <Button type="submit" disabled={!name.trim()}>
              {messages.saveTemplateInfo}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
