import { ImagePlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription } from "@/components/ui/empty";
import type { Locale } from "@/i18n";
import type {
  ResumeTemplateDefinition,
  ResumeTemplateUpdate,
} from "@/types/resume";

import type { TemplateEditorMessages } from "./editor-messages";
import { imageEditorMessages } from "./image-messages";
import { TemplateImageCard } from "./template-image-card";
import { useTemplateImagesEditor } from "./use-template-images-editor";

export function TemplateImagesTab({
  t,
  locale,
  template,
  onUpdateTemplate,
}: {
  t: TemplateEditorMessages;
  locale: Locale;
  template: ResumeTemplateDefinition;
  onUpdateTemplate: (patch: ResumeTemplateUpdate) => void;
}) {
  const editor = useTemplateImagesEditor({ t, template, onUpdateTemplate });
  const messages = imageEditorMessages[locale];

  return (
    <div className="template-control-stack">
      <div className="flex items-center justify-between gap-3">
        <h3 className="flex items-center gap-2 text-xs font-semibold">
          {t.templateImageControls}
          <span className="font-normal tabular-nums text-muted-foreground">
            {template.layout.images.length}
          </span>
        </h3>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="template-image-action shadow-none disabled:pointer-events-auto disabled:cursor-not-allowed"
          aria-label={t.addTemplateImage}
          title={t.addTemplateImage}
          onClick={editor.addImage}
          disabled={editor.isReadonly}
        >
          <ImagePlus data-icon="inline-start" />
          {messages.add}
        </Button>
      </div>

      {template.layout.images.length === 0 ? (
        <Empty className="py-8 md:p-8">
          <EmptyDescription>{messages.empty}</EmptyDescription>
        </Empty>
      ) : null}

      {template.layout.images.map((image, index) => {
        const imageKey = `${template.id}:${image.id}`;
        const nameDraft =
          editor.imageNameDraft?.imageKey === imageKey
            ? editor.imageNameDraft.value
            : null;

        return (
          <TemplateImageCard
            key={imageKey}
            t={t}
            messages={messages}
            image={image}
            index={index}
            isReadonly={editor.isReadonly}
            isExpanded={editor.expandedImageId === image.id}
            nameDraft={nameDraft}
            onCancelNameEdit={editor.cancelImageNameEdit}
            onCommitName={() => editor.commitImageName(image.id)}
            onExpandedChange={(open) => editor.setImageExpanded(image.id, open)}
            onNameDraftChange={(value) =>
              editor.setImageNameDraftValue(image.id, value)
            }
            onRemove={() => editor.removeImage(image.id)}
            onStartNameEdit={() =>
              editor.startImageNameEdit(image.id, image.name)
            }
            onUpdate={(patch) => editor.updateImage(image.id, patch)}
            onUpload={(file) => {
              void editor.uploadImage(image.id, file);
            }}
          />
        );
      })}
    </div>
  );
}
