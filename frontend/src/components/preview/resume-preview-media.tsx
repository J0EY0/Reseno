import { ImageIcon } from "lucide-react";
import { lazy, Suspense } from "react";

import type { TemplateImageGeometry } from "@/lib/template-image-geometry";

import type { AppMessages } from "@/i18n";
import { getInitials } from "@/lib/resume";
import { getRichTextPlainText } from "@/lib/rich-text";
import { cn } from "@/lib/utils";
import type {
  ResumeBasicInfo,
  ResumeTemplateImageElement,
  ResumeTemplateLayout,
} from "@/types/resume";

function getAvatarPlaceholderLabel(src: string, fallbackLabel: string) {
  if (!src.startsWith("data:image/svg+xml")) {
    return null;
  }

  try {
    const decoded = decodeURIComponent(src);

    if (!decoded.includes('data-reseno-avatar-placeholder="true"')) {
      return null;
    }

    return (
      decoded.match(/data-placeholder-label="([^"]*)"/)?.[1] ?? fallbackLabel
    );
  } catch {
    return null;
  }
}

export function AvatarPreview({
  basic,
  className,
  imageClassName,
  layout,
  t,
}: {
  basic: ResumeBasicInfo;
  className: string;
  imageClassName?: string;
  layout: ResumeTemplateLayout;
  t: AppMessages;
}) {
  if (!basic.avatar.trim()) {
    return null;
  }

  const placeholderLabel = getAvatarPlaceholderLabel(
    basic.avatar,
    t.resumePreviewAvatarPlaceholder,
  );
  const isPlaceholder = Boolean(placeholderLabel);
  const placeholderBorderColor =
    layout.avatarBorderWidth > 0
      ? layout.avatarBorderColor
      : layout.basicInfo === "sidebar"
        ? "rgba(255,255,255,0.58)"
        : "rgba(113,113,122,0.36)";
  const placeholderTextColor =
    layout.basicInfo === "sidebar" ? "rgba(255,255,255,0.78)" : "#71717a";
  const placeholderFontSize = `${Math.max(
    14,
    Math.min(28, layout.avatarWidth * 0.9),
  )}px`;

  return (
    <div
      data-avatar-frame="true"
      data-avatar-initials={getInitials(basic.name)}
      className={cn(
        "flex items-center justify-center overflow-hidden bg-transparent font-semibold",
        className,
      )}
      style={{
        width: `${layout.avatarWidth}mm`,
        height: `${layout.avatarHeight}mm`,
        transform:
          layout.avatarOffsetX || layout.avatarOffsetY
            ? `translate(${layout.avatarOffsetX}mm, ${layout.avatarOffsetY}mm)`
            : undefined,
        borderRadius: 0,
        border:
          !isPlaceholder && layout.avatarBorderWidth > 0
            ? `${layout.avatarBorderWidth}px solid ${layout.avatarBorderColor}`
            : undefined,
      }}
    >
      {isPlaceholder ? (
        <div
          data-avatar-placeholder="true"
          className="flex size-full items-center justify-center bg-transparent text-center font-medium tracking-[0.08em]"
          style={{
            border: `${Math.max(1, layout.avatarBorderWidth || 1)}px solid ${placeholderBorderColor}`,
            color: placeholderTextColor,
            fontSize: placeholderFontSize,
          }}
        >
          {placeholderLabel}
        </div>
      ) : (
        <img
          data-avatar-image="true"
          src={basic.avatar}
          alt={getRichTextPlainText(basic.name)}
          className={cn(
            "block size-full object-cover object-center",
            imageClassName,
          )}
          crossOrigin="anonymous"
          loading="eager"
          decoding="sync"
          draggable={false}
        />
      )}
    </div>
  );
}

function TemplateImageContent({
  image,
}: {
  image: ResumeTemplateImageElement;
}) {
  return (
    <div
      className="flex size-full items-center justify-center overflow-hidden text-center text-[9px] font-medium text-neutral-400"
      style={{
        opacity: image.opacity,
        borderWidth: image.borderWidth,
        borderColor: image.borderColor,
        borderStyle: image.borderWidth > 0 ? "solid" : "none",
        borderRadius: image.borderRadius,
        backgroundColor: image.src ? undefined : "rgb(255 255 255 / 0.1)",
      }}
    >
      {image.src ? (
        <img
          src={image.src}
          alt={image.alt || image.name}
          className="size-full"
          style={{ objectFit: image.objectFit }}
          crossOrigin="anonymous"
          draggable={false}
        />
      ) : (
        <div className="flex size-full flex-col items-center justify-center gap-1 px-1">
          <ImageIcon className="size-3 opacity-60" strokeWidth={1.75} />
          <span className="max-w-full truncate leading-none text-neutral-500/80">
            {image.name}
          </span>
        </div>
      )}
    </div>
  );
}

function TemplateImageFrame({ image }: { image: ResumeTemplateImageElement }) {
  return (
    <div
      data-template-image-frame="true"
      className="absolute"
      style={{
        left: `${image.x}mm`,
        top: `${image.y}mm`,
        width: `${image.width}mm`,
        height: `${image.height}mm`,
      }}
    >
      <TemplateImageContent image={image} />
    </div>
  );
}

const TemplateImageEditor = lazy(() => import("./template-image-editor"));

export function TemplateImages({
  editable = false,
  images,
  onChangeImage,
  showEmptyPlaceholders = false,
}: {
  editable?: boolean;
  images: ResumeTemplateImageElement[];
  onChangeImage?: (imageId: string, geometry: TemplateImageGeometry) => void;
  showEmptyPlaceholders?: boolean;
}) {
  const visibleImages = images.filter(
    (image) =>
      image.visible && (showEmptyPlaceholders || image.src.trim().length > 0),
  );
  if (visibleImages.length === 0) return null;

  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-0",
        editable ? "z-20" : "z-0",
      )}
    >
      {visibleImages.map((image) => {
        const frame = <TemplateImageFrame key={image.id} image={image} />;
        return editable && onChangeImage ? (
          <Suspense key={image.id} fallback={frame}>
            <TemplateImageEditor image={image} onChange={onChangeImage}>
              <TemplateImageContent image={image} />
            </TemplateImageEditor>
          </Suspense>
        ) : (
          frame
        );
      })}
    </div>
  );
}
