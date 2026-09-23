import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import type { AppMessages } from "@/i18n";
import { createTemplateImageElement } from "@/lib/templates";
import type {
  ResumeTemplateDefinition,
  ResumeTemplateUpdate,
  ResumeTemplateImageElement,
  ResumeTemplateLayout,
} from "@/types/resume";

export function useTemplateImagesEditor({
  t,
  template,
  onUpdateTemplate,
}: {
  t: AppMessages;
  template: ResumeTemplateDefinition;
  onUpdateTemplate: (patch: ResumeTemplateUpdate) => void;
}) {
  const isReadonly = Boolean(template.isBuiltIn);
  const uploadsRef = useRef(new Map<string, symbol>());
  useEffect(() => {
    const uploads = uploadsRef.current;
    return () => uploads.clear();
  }, []);
  const [expandedImageIdByTemplate, setExpandedImageIdByTemplate] = useState<
    Partial<Record<string, string>>
  >({});
  const [imageNameDraft, setImageNameDraft] = useState<{
    imageKey: string;
    value: string;
  } | null>(null);

  function updateLayout(patch: Partial<ResumeTemplateLayout>) {
    if (isReadonly) {
      return;
    }

    onUpdateTemplate({
      layout: {
        ...template.layout,
        ...patch,
      },
    });
  }

  function addImage() {
    if (isReadonly) {
      return;
    }

    const currentImages = template.layout.images;
    const currentImageNames = new Set(currentImages.map((image) => image.name));
    let nextImageIndex = 1;

    while (currentImageNames.has(`${t.imageDefaultName} ${nextImageIndex}`)) {
      nextImageIndex += 1;
    }

    const nextImage = createTemplateImageElement(
      nextImageIndex,
      t.imageDefaultName,
      template.layout,
    );
    setExpandedImageIdByTemplate((current) => ({
      ...current,
      [template.id]: nextImage.id,
    }));
    updateLayout({ images: [...currentImages, nextImage] });
  }

  function updateImage(
    imageId: string,
    patch:
      | Partial<ResumeTemplateImageElement>
      | ((
          image: ResumeTemplateImageElement,
        ) => Partial<ResumeTemplateImageElement>),
  ) {
    if (isReadonly) {
      return;
    }

    onUpdateTemplate((current) => ({
      layout: {
        ...current.layout,
        images: current.layout.images.map((image) =>
          image.id === imageId
            ? {
                ...image,
                ...(typeof patch === "function" ? patch(image) : patch),
              }
            : image,
        ),
      },
    }));
  }

  function setImageNameDraftValue(imageId: string, value: string) {
    const imageKey = `${template.id}:${imageId}`;
    setImageNameDraft((current) =>
      current?.imageKey === imageKey ? { ...current, value } : current,
    );
  }

  function startImageNameEdit(imageId: string, value: string) {
    setImageNameDraft({ imageKey: `${template.id}:${imageId}`, value });
  }

  function commitImageName(imageId: string) {
    const imageKey = `${template.id}:${imageId}`;
    if (imageNameDraft?.imageKey !== imageKey) {
      return;
    }

    updateImage(imageId, { name: imageNameDraft.value });
    setImageNameDraft(null);
  }

  function removeImage(imageId: string) {
    if (isReadonly) {
      return;
    }

    const imageKey = `${template.id}:${imageId}`;
    uploadsRef.current.delete(imageKey);
    setExpandedImageIdByTemplate((current) => {
      if (current[template.id] !== imageId) {
        return current;
      }

      const next = { ...current };
      delete next[template.id];
      return next;
    });
    setImageNameDraft((current) =>
      current?.imageKey === imageKey ? null : current,
    );
    updateLayout({
      images: template.layout.images.filter((image) => image.id !== imageId),
    });
  }

  function setImageExpanded(imageId: string, open: boolean) {
    setExpandedImageIdByTemplate((current) => {
      if (open) {
        return { ...current, [template.id]: imageId };
      }

      if (current[template.id] !== imageId) {
        return current;
      }

      const next = { ...current };
      delete next[template.id];
      return next;
    });
  }

  async function uploadImage(imageId: string, file: File | undefined) {
    const original = template.layout.images.find(
      (image) => image.id === imageId,
    );
    if (!file || !original || isReadonly) {
      return;
    }
    const imageKey = `${template.id}:${imageId}`;
    const upload = Symbol();
    uploadsRef.current.set(imageKey, upload);
    try {
      const { prepareTemplateImage } =
        await import("@/lib/template-image-upload");
      const src = await prepareTemplateImage(file);
      if (uploadsRef.current.get(imageKey) !== upload) {
        return;
      }
      updateImage(imageId, (current) => ({
        src,
        alt: file.name,
        name:
          current.name === original.name
            ? file.name.replace(/\.[^.]+$/, "") || file.name
            : current.name,
      }));
    } catch (error) {
      if (uploadsRef.current.get(imageKey) !== upload) {
        return;
      }
      console.error("Failed to import template image.", error);
      const messageKey = error instanceof Error ? error.message : "";
      const message =
        Object.hasOwn(t, messageKey) && messageKey.startsWith("templateImage")
          ? t[messageKey as keyof AppMessages]
          : t.templateImageProcessingFailed;
      toast.error(
        typeof message === "string" ? message : t.templateImageProcessingFailed,
        { closeButton: true },
      );
    } finally {
      if (uploadsRef.current.get(imageKey) === upload) {
        uploadsRef.current.delete(imageKey);
      }
    }
  }

  return {
    addImage,
    cancelImageNameEdit: () => setImageNameDraft(null),
    commitImageName,
    expandedImageId: expandedImageIdByTemplate[template.id],
    imageNameDraft,
    isReadonly,
    removeImage,
    setImageExpanded,
    setImageNameDraftValue,
    startImageNameEdit,
    updateImage,
    uploadImage,
  };
}
