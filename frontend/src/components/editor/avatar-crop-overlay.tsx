import { cn } from "@/lib/utils";

import type {
  AvatarCropRect,
  AvatarCropStageSize,
} from "./avatar-crop-geometry";

export function AvatarCropOverlay({
  crop,
  stageSize,
  isMoving,
}: {
  crop: AvatarCropRect;
  stageSize: AvatarCropStageSize;
  isMoving: boolean;
}) {
  return (
    <>
      <div
        className="pointer-events-none absolute left-0 top-0 bg-black/60"
        style={{ width: stageSize.width, height: crop.y }}
      />
      <div
        className="pointer-events-none absolute left-0 bg-black/60"
        style={{ top: crop.y, width: crop.x, height: crop.height }}
      />
      <div
        className="pointer-events-none absolute bg-black/60"
        style={{
          left: crop.x + crop.width,
          top: crop.y,
          width: stageSize.width - crop.x - crop.width,
          height: crop.height,
        }}
      />
      <div
        className="pointer-events-none absolute left-0 bg-black/60"
        style={{
          top: crop.y + crop.height,
          width: stageSize.width,
          height: stageSize.height - crop.y - crop.height,
        }}
      />
      <div
        className={cn(
          "pointer-events-none absolute border-2 border-dashed border-white/95",
          isMoving && "shadow-[0_0_0_1px_rgba(255,255,255,0.3)]",
        )}
        style={{
          left: crop.x,
          top: crop.y,
          width: crop.width,
          height: crop.height,
        }}
      >
        <div className="absolute inset-0 ring-1 ring-inset ring-black/8" />
        <div className="absolute inset-x-[33%] top-0 h-full border-l border-r border-white/45" />
        <div className="absolute inset-y-[33%] left-0 w-full border-t border-b border-white/45" />
        <div className="absolute -left-1.5 -top-1.5 size-3 rounded-full border border-white bg-background/90" />
        <div className="absolute -right-1.5 -top-1.5 size-3 rounded-full border border-white bg-background/90" />
        <div className="absolute -bottom-1.5 -left-1.5 size-3 rounded-full border border-white bg-background/90" />
        <div className="absolute -bottom-2 -right-2 size-4 rounded-full border border-white bg-background shadow-sm" />
      </div>
    </>
  );
}
