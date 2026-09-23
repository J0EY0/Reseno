import {
  ChevronDown,
  MoreHorizontal,
  PencilLine,
  Trash2,
  Upload,
} from "lucide-react";
import { useRef } from "react";

import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import type { AppMessages } from "@/i18n";
import type { ResumeTemplateImageElement } from "@/types/resume";

import type { ImageEditorMessages } from "./image-messages";
import { TemplateImageFieldControls } from "./template-image-field-controls";

type TemplateImageCardProps = {
  t: AppMessages;
  messages: ImageEditorMessages;
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

function TemplateImageThumbnail({
  image,
}: {
  image: ResumeTemplateImageElement;
}) {
  return (
    <span
      data-slot="template-image-thumbnail"
      className="flex size-5 shrink-0 items-center justify-center overflow-hidden rounded border bg-background"
      style={{
        borderColor: image.borderColor,
        borderWidth: image.borderWidth,
        borderRadius: image.borderRadius,
      }}
    >
      <img
        src={image.src}
        alt={image.alt || image.name}
        className="size-full"
        style={{ objectFit: image.objectFit }}
        draggable={false}
      />
    </span>
  );
}

function TemplateImageCardHeader({
  t,
  messages,
  image,
  index,
  isReadonly,
  isExpanded,
  nameDraft,
  onCancelNameEdit,
  onCommitName,
  onNameDraftChange,
  onRemove,
  onStartNameEdit,
  onUpload,
}: Omit<TemplateImageCardProps, "onExpandedChange" | "onUpdate">) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const renamingRef = useRef(false);
  const imageNameInputId = `template-image-${image.id}-name`;

  return (
    <div
      data-slot="template-image-card-header"
      className="-mx-0.5 flex min-w-0 items-center gap-2 py-1"
    >
      {nameDraft !== null ? (
        <Field orientation="horizontal" className="min-w-0 flex-1 gap-2">
          <FieldLabel htmlFor={imageNameInputId} className="sr-only">
            {t.imageName}
          </FieldLabel>
          <Input
            id={imageNameInputId}
            value={nameDraft}
            onChange={(event) => onNameDraftChange(event.target.value)}
            onBlur={onCommitName}
            onKeyDown={(event) => {
              if (event.key === "Enter") event.currentTarget.blur();
              if (event.key === "Escape") {
                event.preventDefault();
                onCancelNameEdit();
              }
            }}
            placeholder={`${t.imageName} ${index + 1}`}
            className="template-control min-w-0"
            autoFocus
          />
        </Field>
      ) : (
        <CollapsibleTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            className="template-image-summary h-8 min-w-0 flex-1 justify-start gap-1.5 px-0 has-[>svg]:px-0"
            aria-label={
              isExpanded ? t.collapseImageSettings : t.expandImageSettings
            }
          >
            <span
              className="truncate text-[13px] font-semibold"
              title={image.name}
            >
              {image.name || `${t.imageName} ${index + 1}`}
            </span>
            <ChevronDown data-icon="inline-end" aria-hidden="true" />
          </Button>
        </CollapsibleTrigger>
      )}
      <Input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        disabled={isReadonly}
        aria-label={t.imageSourceLabel}
        onChange={(event) => {
          onUpload(event.target.files?.[0]);
          event.target.value = "";
        }}
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="template-image-action shadow-none"
        onClick={() => fileInputRef.current?.click()}
        disabled={isReadonly}
        aria-label={image.src ? t.replaceImage : t.uploadImage}
        title={image.src ? t.replaceImage : t.uploadImage}
      >
        {image.src ? (
          <TemplateImageThumbnail image={image} />
        ) : (
          <Upload data-icon="inline-start" aria-hidden="true" />
        )}
        {image.src ? messages.replace : messages.upload}
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={t.moreActions}
            disabled={isReadonly}
          >
            <MoreHorizontal data-icon="icon-only" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          onCloseAutoFocus={(event) => {
            if (renamingRef.current) {
              event.preventDefault();
              renamingRef.current = false;
              onStartNameEdit();
            }
          }}
        >
          <DropdownMenuGroup>
            <DropdownMenuItem
              onSelect={() => {
                renamingRef.current = true;
              }}
            >
              <PencilLine />
              {t.editImageName}
            </DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onSelect={onRemove}>
              <Trash2 />
              {t.removeImage}
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

export function TemplateImageCard(props: TemplateImageCardProps) {
  const {
    t,
    messages,
    image,
    index,
    isReadonly,
    isExpanded,
    onExpandedChange,
    onUpdate,
  } = props;
  return (
    <Collapsible
      open={isExpanded}
      onOpenChange={onExpandedChange}
      role="group"
      aria-label={`${t.templateImageControls} ${index + 1}`}
      className="template-image-item min-w-0 px-0.5"
    >
      <TemplateImageCardHeader {...props} />
      <CollapsibleContent inert={!isExpanded} className="collapsible-content">
        <TemplateImageFieldControls
          t={t}
          messages={messages}
          image={image}
          fileInputId={`template-image-${image.id}`}
          isReadonly={isReadonly}
          onUpdate={onUpdate}
        />
      </CollapsibleContent>
    </Collapsible>
  );
}
