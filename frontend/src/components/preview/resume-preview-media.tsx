import { ImageIcon } from "lucide-react";
import { useRef, type PointerEvent } from "react";

import type { AppMessages } from "@/i18n";
import { getInitials } from "@/lib/resume";
import { getRichTextPlainText } from "@/lib/rich-text";
import { cn } from "@/lib/utils";
import type {
  ResumeBasicInfo,
  ResumeTemplateImageElement,
  ResumeTemplateLayout,
} from "@/types/resume";

function getAvatarBorderRadius(layout: ResumeTemplateLayout) {
  if (layout.avatarShape === "circle") {
    return "9999px";
  }

  if (layout.avatarShape === "square") {
    return "4px";
  }

  return "14px";
}

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
        borderRadius: getAvatarBorderRadius(layout),
        border:
          !isPlaceholder && layout.avatarBorderWidth > 0
            ? `${layout.avatarBorderWidth}px solid ${layout.avatarBorderColor}`
            : undefined,
      }}
    >
      {isPlaceholder ? (
        <div
          data-avatar-placeholder="true"
          className="flex size-full items-center justify-center rounded-[inherit] bg-transparent text-center font-medium tracking-[0.08em]"
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

function clampNumber(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function roundToHalf(value: number) {
  return Math.round(value * 2) / 2;
}

export function TemplateImages({
  editable = false,
  images,
  onMoveImage,
  showEmptyPlaceholders = false,
}: {
  editable?: boolean;
  images: ResumeTemplateImageElement[];
  onMoveImage?: (
    imageId: string,
    patch: Pick<ResumeTemplateImageElement, "x" | "y">,
  ) => void;
  showEmptyPlaceholders?: boolean;
}) {
  const dragStateRef = useRef<{
    imageId: string;
    pointerId: number;
    startClientX: number;
    startClientY: number;
    startX: number;
    startY: number;
    width: number;
    height: number;
    pxPerMm: number;
  } | null>(null);
  const visibleImages = images.filter(
    (image) =>
      image.visible && (showEmptyPlaceholders || image.src.trim().length > 0),
  );

  if (visibleImages.length === 0) {
    return null;
  }

  function handlePointerDown(
    event: PointerEvent<HTMLDivElement>,
    frame: ResumeTemplateImageElement,
  ) {
    if (!editable || !onMoveImage || event.button !== 0) {
      return;
    }

    const pageElement = event.currentTarget.closest(
      '[data-export-root="resume-page"]',
    ) as HTMLElement | null;
    const pageRect = pageElement?.getBoundingClientRect();
    const pxPerMm =
      pageRect && pageRect.width > 0
        ? pageRect.width / 210
        : event.currentTarget.getBoundingClientRect().width / frame.width;

    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);

    dragStateRef.current = {
      imageId: frame.id,
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      startX: frame.x,
      startY: frame.y,
      width: frame.width,
      height: frame.height,
      pxPerMm,
    };
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>) {
    const dragState = dragStateRef.current;

    if (!dragState || !onMoveImage || dragState.pointerId !== event.pointerId) {
      return;
    }

    event.preventDefault();

    const nextX = clampNumber(
      roundToHalf(
        dragState.startX +
          (event.clientX - dragState.startClientX) / dragState.pxPerMm,
      ),
      0,
      Math.max(0, 210 - dragState.width),
    );
    const nextY = clampNumber(
      roundToHalf(
        dragState.startY +
          (event.clientY - dragState.startClientY) / dragState.pxPerMm,
      ),
      0,
      Math.max(0, 297 - dragState.height),
    );

    onMoveImage(dragState.imageId, { x: nextX, y: nextY });
  }

  function handlePointerUp(event: PointerEvent<HTMLDivElement>) {
    const dragState = dragStateRef.current;

    if (!dragState || dragState.pointerId !== event.pointerId) {
      return;
    }

    event.currentTarget.releasePointerCapture(event.pointerId);
    dragStateRef.current = null;
  }

  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-0",
        editable ? "z-20" : "z-0",
      )}
    >
      {visibleImages.map((frame) => (
        <div
          key={frame.id}
          data-template-image-frame="true"
          className={cn(
            "absolute flex min-h-6 min-w-6 items-center justify-center overflow-hidden text-center text-[9px] font-medium text-neutral-400",
            !frame.src && "bg-white/10",
            editable &&
              "pointer-events-auto cursor-grab touch-none transition-[box-shadow,outline-color] active:cursor-grabbing hover:shadow-sm",
          )}
          style={{
            left: `${frame.x}mm`,
            top: `${frame.y}mm`,
            width: `${frame.width}mm`,
            height: `${frame.height}mm`,
            opacity: frame.opacity,
            borderWidth: `${frame.borderWidth}px`,
            borderColor: frame.borderColor,
            borderStyle: frame.borderWidth > 0 ? "solid" : "none",
            borderRadius: `${frame.borderRadius}px`,
          }}
          onPointerDown={(event) => handlePointerDown(event, frame)}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
        >
          {frame.src ? (
            <img
              src={frame.src}
              alt={frame.alt || frame.name}
              className="size-full"
              style={{ objectFit: frame.objectFit }}
              crossOrigin="anonymous"
              draggable={false}
            />
          ) : (
            <div className="flex size-full flex-col items-center justify-center gap-1 rounded-[inherit] bg-transparent px-1">
              <ImageIcon className="size-3 opacity-60" strokeWidth={1.75} />
              <span className="max-w-full truncate leading-none text-neutral-500/80">
                {frame.name}
              </span>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
