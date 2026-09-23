import {
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";

import type { AppMessages } from "@/i18n";
import { cn } from "@/lib/utils";

import {
  avatarCropAspectRatio,
  avatarCropHandleHitArea,
  avatarCropMinWidth,
  clampAvatarCrop,
  createAspectAvatarCrop,
  isPointInAvatarCrop,
  type AvatarCropRect,
} from "./avatar-crop-geometry";
import { AvatarCropOverlay } from "./avatar-crop-overlay";
import type { AvatarCropController } from "./use-avatar-crop";

type InteractionMode = "draw" | "move" | "resize" | null;

export function AvatarCropCanvas({
  t,
  source,
  controller,
}: {
  t: AppMessages;
  source: string;
  controller: AvatarCropController;
}) {
  const [interactionMode, setInteractionMode] = useState<InteractionMode>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const dragStateRef = useRef<{
    pointerId: number;
    mode: Exclude<InteractionMode, null>;
    startPoint: { x: number; y: number };
    originCrop: AvatarCropRect;
  } | null>(null);
  const { crop, hasCrop, stageSize } = controller;

  function getStagePoint(event: ReactPointerEvent<HTMLDivElement>) {
    const bounds = stageRef.current?.getBoundingClientRect();
    if (!bounds) {
      return { x: 0, y: 0 };
    }

    return {
      x: clampAvatarCrop(event.clientX - bounds.left, 0, bounds.width),
      y: clampAvatarCrop(event.clientY - bounds.top, 0, bounds.height),
    };
  }

  function handlePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (!stageSize.width || !stageSize.height || controller.isSaving) {
      return;
    }

    const point = getStagePoint(event);
    const handleRect = {
      x: crop.x + crop.width - avatarCropHandleHitArea / 2,
      y: crop.y + crop.height - avatarCropHandleHitArea / 2,
      width: avatarCropHandleHitArea,
      height: avatarCropHandleHitArea,
    };
    const targetMode =
      hasCrop && isPointInAvatarCrop(point, handleRect)
        ? "resize"
        : hasCrop && isPointInAvatarCrop(point, crop)
          ? "move"
          : "draw";

    setInteractionMode(targetMode);
    dragStateRef.current = {
      pointerId: event.pointerId,
      mode: targetMode,
      startPoint: point,
      originCrop: crop,
    };
    if (targetMode === "draw") {
      controller.onCropChange({ x: point.x, y: point.y, width: 0, height: 0 });
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const dragState = dragStateRef.current;
    if (!dragState || dragState.pointerId !== event.pointerId) {
      return;
    }

    const point = getStagePoint(event);
    if (dragState.mode === "draw") {
      controller.onCropChange(
        createAspectAvatarCrop(dragState.startPoint, point, stageSize),
      );
      return;
    }
    if (dragState.mode === "move") {
      controller.onCropChange({
        x: clampAvatarCrop(
          dragState.originCrop.x + point.x - dragState.startPoint.x,
          0,
          stageSize.width - dragState.originCrop.width,
        ),
        y: clampAvatarCrop(
          dragState.originCrop.y + point.y - dragState.startPoint.y,
          0,
          stageSize.height - dragState.originCrop.height,
        ),
        width: dragState.originCrop.width,
        height: dragState.originCrop.height,
      });
      return;
    }

    const widthFromX =
      dragState.originCrop.width + point.x - dragState.startPoint.x;
    const widthFromY =
      dragState.originCrop.width +
      (point.y - dragState.startPoint.y) * avatarCropAspectRatio;
    const maxWidth = Math.min(
      stageSize.width - dragState.originCrop.x,
      (stageSize.height - dragState.originCrop.y) * avatarCropAspectRatio,
    );
    const nextWidth = clampAvatarCrop(
      Math.max(widthFromX, widthFromY),
      avatarCropMinWidth,
      maxWidth,
    );
    controller.onCropChange({
      x: dragState.originCrop.x,
      y: dragState.originCrop.y,
      width: nextWidth,
      height: nextWidth / avatarCropAspectRatio,
    });
  }

  function handlePointerEnd(event: ReactPointerEvent<HTMLDivElement>) {
    const dragState = dragStateRef.current;
    if (!dragState || dragState.pointerId !== event.pointerId) {
      return;
    }

    if (dragState.mode === "draw") {
      controller.onCropChange((current) =>
        current.width >= avatarCropMinWidth
          ? current
          : { x: 0, y: 0, width: 0, height: 0 },
      );
    }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    dragStateRef.current = null;
    setInteractionMode(null);
  }

  return (
    <div className="flex items-center justify-center">
      <div className="relative flex min-h-[420px] w-full items-center justify-center overflow-hidden rounded-(--radius-preview) border border-border bg-muted/30 p-4">
        <div
          ref={stageRef}
          className={cn(
            "relative overflow-hidden select-none touch-none",
            interactionMode === "draw"
              ? "cursor-crosshair"
              : interactionMode === "move"
                ? "cursor-grabbing"
                : interactionMode === "resize"
                  ? "cursor-se-resize"
                  : hasCrop
                    ? "cursor-default"
                    : "cursor-crosshair",
          )}
          style={{
            width: stageSize.width || undefined,
            height: stageSize.height || undefined,
          }}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerEnd}
          onPointerCancel={handlePointerEnd}
        >
          <img
            src={source}
            alt={t.cropAvatar}
            className="block size-full object-contain"
            onLoad={(event) =>
              controller.onImageLoad(
                event.currentTarget.naturalWidth,
                event.currentTarget.naturalHeight,
              )
            }
            draggable={false}
          />
          {hasCrop ? (
            <AvatarCropOverlay
              crop={crop}
              stageSize={stageSize}
              isMoving={interactionMode === "move"}
            />
          ) : (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <div className="rounded-full border border-white/70 bg-black/55 px-4 py-2 text-sm font-medium text-white">
                {t.cropAvatarHint}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
