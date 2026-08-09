import { useState } from "react";

import type { AppMessages } from "@/i18n";
import { readAvatarFileAsDataUrl } from "@/lib/avatar";
import { createId } from "@/lib/resume";
import type {
  ResumeTemplateDefinition,
  ResumeTemplateImageElement,
  ResumeTemplateLayout,
} from "@/types/resume";

function createTemplateImageElement(
  index: number,
  defaultName: string,
  layout?: ResumeTemplateLayout,
): ResumeTemplateImageElement {
  const placeOnLeft = layout?.avatarPosition === "right";

  return {
    id: createId("image"),
    name: `${defaultName} ${index}`,
    src: "",
    alt: "",
    x: placeOnLeft ? 14 : 166,
    y: 18,
    width: 30,
    height: 20,
    opacity: 1,
    borderWidth: 0.8,
    borderColor: "#d4d4d8",
    borderRadius: 8,
    objectFit: "contain",
    visible: true,
  };
}

export function useTemplateImagesEditor({
  t,
  template,
  onUpdateTemplate,
}: {
  t: AppMessages;
  template: ResumeTemplateDefinition;
  onUpdateTemplate: (patch: Partial<ResumeTemplateDefinition>) => void;
}) {
  const isReadonly = Boolean(template.isBuiltIn);
  // This hook is called above Radix TabsContent so editor-only expansion and
  // name drafts survive tab switches without leaking into saved template data.
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
    patch: Partial<ResumeTemplateImageElement>,
  ) {
    if (isReadonly) {
      return;
    }

    updateLayout({
      images: template.layout.images.map((image) =>
        image.id === imageId ? { ...image, ...patch } : image,
      ),
    });
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
    if (!file) {
      return;
    }

    try {
      const src = await readAvatarFileAsDataUrl(file);
      updateImage(imageId, {
        src,
        alt: file.name,
        name: file.name.replace(/\.[^.]+$/, "") || file.name,
      });
    } catch (error) {
      console.error("Failed to import template image.", error);
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
