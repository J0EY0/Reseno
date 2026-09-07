import { ImagePlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { TabsContent } from "@/components/ui/tabs";
import type { AppMessages } from "@/i18n";
import { cn } from "@/lib/utils";
import type {
  ResumeTemplateDefinition,
  ResumeTemplateUpdate,
} from "@/types/resume";

import { readonlyDisabledControlClassName } from "./editor-values";
import { TemplateImageCard } from "./template-image-card";
import { useTemplateImagesEditor } from "./use-template-images-editor";

export function TemplateImagesTab({
  t,
  template,
  onUpdateTemplate,
}: {
  t: AppMessages;
  template: ResumeTemplateDefinition;
  onUpdateTemplate: (patch: ResumeTemplateUpdate) => void;
}) {
  const editor = useTemplateImagesEditor({ t, template, onUpdateTemplate });

  return (
    <TabsContent
      value="images"
      className={cn(
        "m-0 grid gap-3 px-1 py-4",
        editor.isReadonly && "opacity-70",
      )}
    >
      <Button
        type="button"
        variant="outline"
        className={cn(
          "h-11 justify-center rounded-xl border-dashed bg-background",
          readonlyDisabledControlClassName,
        )}
        onClick={editor.addImage}
        disabled={editor.isReadonly}
      >
        <ImagePlus data-icon="inline-start" />
        {t.addTemplateImage}
      </Button>

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
            image={image}
            index={index}
            isReadonly={editor.isReadonly}
            isExpanded={editor.expandedImageId === image.id}
            nameDraft={nameDraft}
            onCancelNameEdit={editor.cancelImageNameEdit}
            onCommitName={() => editor.commitImageName(image.id)}
            onExpandedChange={(open) =>
              editor.setImageExpanded(image.id, open)
            }
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
    </TabsContent>
  );
}
