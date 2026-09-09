export const avatarCropAspectRatio = 4 / 5;
export const avatarCropMinWidth = 92;
export const avatarCropHandleHitArea = 18;

export type AvatarCropRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type AvatarCropStageSize = {
  width: number;
  height: number;
};

export function clampAvatarCrop(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export function isPointInAvatarCrop(
  point: { x: number; y: number },
  rect: AvatarCropRect,
) {
  return (
    point.x >= rect.x &&
    point.x <= rect.x + rect.width &&
    point.y >= rect.y &&
    point.y <= rect.y + rect.height
  );
}

export function createAspectAvatarCrop(
  start: { x: number; y: number },
  end: { x: number; y: number },
  stage: AvatarCropStageSize,
) {
  const deltaX = end.x - start.x;
  const deltaY = end.y - start.y;
  const directionX = deltaX < 0 ? -1 : 1;
  const directionY = deltaY < 0 ? -1 : 1;
  const availableWidth = directionX < 0 ? start.x : stage.width - start.x;
  const availableHeight = directionY < 0 ? start.y : stage.height - start.y;
  const maxWidth = Math.min(
    availableWidth,
    availableHeight * avatarCropAspectRatio,
  );
  const width = clampAvatarCrop(
    Math.max(Math.abs(deltaX), Math.abs(deltaY) * avatarCropAspectRatio),
    0,
    maxWidth,
  );

  return {
    x: directionX < 0 ? start.x - width : start.x,
    y: directionY < 0 ? start.y - width / avatarCropAspectRatio : start.y,
    width,
    height: width / avatarCropAspectRatio,
  };
}
