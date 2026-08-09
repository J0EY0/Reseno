import { ChevronDown, ImagePlus, PencilLine, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import type { AppMessages } from "@/i18n";
import { cn } from "@/lib/utils";
import type { ResumeTemplateImageElement } from "@/types/resume";

import { readonlyDisabledControlClassName } from "./editor-values";
import { TemplateImageFieldControls } from "./template-image-field-controls";

type TemplateImageCardProps = {
  t: AppMessages;
  image: ResumeTemplateImageElement;
  index: number;
  isReadonly: boolean;
  isExpanded: boolean;
  nameDraft: string | null;
  onCancelNameEdit: () => void;
  onCommitName: () => void;
  onExpandedChange: (open: boolean) => void;
  onNameDraftChange: (value: string) => void;
  onRemove: () => void;
  onStartNameEdit: () => void;
  onUpdate: (patch: Partial<ResumeTemplateImageElement>) => void;
  onUpload: (file: File | undefined) => void;
};

function TemplateImageCardHeader({
  t,
  image,
  index,
  isReadonly,
  nameDraft,
  onCancelNameEdit,
  onCommitName,
  onNameDraftChange,
  onRemove,
  onStartNameEdit,
}: Omit<
  TemplateImageCardProps,
  "isExpanded" | "onExpandedChange" | "onUpdate" | "onUpload"
>) {
  const imageNameInputId = `template-image-${image.id}-name`;

  return (
    <div
      data-slot="template-image-card-header"
      className="grid grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-3 p-3"
    >
      <div
        data-slot="template-image-thumbnail"
        className="flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-md border bg-background text-muted-foreground"
        style={{
          borderColor: image.borderColor,
          borderWidth: image.borderWidth,
          borderRadius: image.borderRadius,
        }}
      >
        {image.src ? (
          <img
            src={image.src}
            alt={image.alt || image.name}
            className="size-full"
            style={{ objectFit: image.objectFit }}
            draggable={false}
          />
        ) : (
          <ImagePlus className="size-4 opacity-70" />
        )}
      </div>

      {nameDraft !== null ? (
        <Field className="min-w-0 gap-1.5">
          <FieldLabel htmlFor={imageNameInputId} className="sr-only">
            {t.imageName}
          </FieldLabel>
          <Input
            id={imageNameInputId}
            value={nameDraft}
            onChange={(event) => onNameDraftChange(event.target.value)}
            onBlur={onCommitName}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.currentTarget.blur();
              }

              if (event.key === "Escape") {
                event.preventDefault();
                onCancelNameEdit();
              }
            }}
            placeholder={`${t.imageName} ${index + 1}`}
            autoFocus
            className="font-medium"
          />
        </Field>
      ) : (
        <div className="flex min-w-0 items-center gap-1">
          <p
            className="min-w-0 truncate text-sm font-semibold"
            title={image.name}
          >
            {image.name || `${t.imageName} ${index + 1}`}
          </p>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="shrink-0 text-muted-foreground"
            onClick={onStartNameEdit}
            aria-label={t.editImageName}
            disabled={isReadonly}
          >
            <PencilLine data-icon="icon-only" />
          </Button>
        </div>
      )}

      <div className="flex items-center gap-1">
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className={cn(
            "shrink-0 text-muted-foreground hover:text-destructive",
            readonlyDisabledControlClassName,
          )}
          onClick={onRemove}
          aria-label={t.removeImage}
          disabled={isReadonly}
        >
          <Trash2 data-icon="icon-only" />
        </Button>
        <CollapsibleTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="group shrink-0 text-muted-foreground"
          >
            <ChevronDown
              data-icon="icon-only"
              aria-hidden="true"
              className="transition-transform group-data-[state=open]:rotate-180"
            />
            <span className="sr-only group-data-[state=open]:hidden">
              {t.expandImageSettings}
            </span>
            <span className="sr-only hidden group-data-[state=open]:inline">
              {t.collapseImageSettings}
            </span>
          </Button>
        </CollapsibleTrigger>
      </div>
    </div>
  );
}

export function TemplateImageCard({
  t,
  image,
  index,
  isReadonly,
  isExpanded,
  nameDraft,
  onCancelNameEdit,
  onCommitName,
  onExpandedChange,
  onNameDraftChange,
  onRemove,
  onStartNameEdit,
  onUpdate,
  onUpload,
}: TemplateImageCardProps) {
  const fileInputId = `template-image-${image.id}`;

  return (
    <Collapsible
      open={isExpanded}
      onOpenChange={onExpandedChange}
      role="group"
      aria-label={`${t.templateImageControls} ${index + 1}`}
      className="@container/image-card overflow-hidden rounded-lg bg-muted/35 shadow-xs"
    >
      <TemplateImageCardHeader
        t={t}
        image={image}
        index={index}
        isReadonly={isReadonly}
        nameDraft={nameDraft}
        onCancelNameEdit={onCancelNameEdit}
        onCommitName={onCommitName}
        onNameDraftChange={onNameDraftChange}
        onRemove={onRemove}
        onStartNameEdit={onStartNameEdit}
      />
      <CollapsibleContent className="collapsible-content">
        <TemplateImageFieldControls
          t={t}
          image={image}
          fileInputId={fileInputId}
          isReadonly={isReadonly}
          onUpdate={onUpdate}
          onUpload={onUpload}
        />
      </CollapsibleContent>
    </Collapsible>
  );
}
