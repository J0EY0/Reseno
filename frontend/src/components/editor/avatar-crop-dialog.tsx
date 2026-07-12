import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from 'react'

import type { AppMessages } from '@/i18n'
import { cropAvatarDataUrl } from '@/lib/avatar'
import { cn } from '@/lib/utils'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

const maxStageWidth = 520
const maxStageHeight = 420
const cropAspectRatio = 4 / 5
const minCropWidth = 92
const previewWidth = 108
const previewHeight = Math.round(previewWidth / cropAspectRatio)
const handleHitArea = 18

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function pointInRect(
  point: { x: number; y: number },
  rect: { x: number; y: number; width: number; height: number },
) {
  return (
    point.x >= rect.x &&
    point.x <= rect.x + rect.width &&
    point.y >= rect.y &&
    point.y <= rect.y + rect.height
  )
}

function createAspectCrop(
  start: { x: number; y: number },
  end: { x: number; y: number },
  stage: { width: number; height: number },
) {
  const deltaX = end.x - start.x
  const deltaY = end.y - start.y
  const directionX = deltaX < 0 ? -1 : 1
  const directionY = deltaY < 0 ? -1 : 1
  const availableWidth =
    directionX < 0 ? start.x : stage.width - start.x
  const availableHeight =
    directionY < 0 ? start.y : stage.height - start.y
  const maxWidth = Math.min(availableWidth, availableHeight * cropAspectRatio)
  const widthFromX = Math.abs(deltaX)
  const widthFromY = Math.abs(deltaY) * cropAspectRatio
  const width = clamp(Math.max(widthFromX, widthFromY), 0, maxWidth)
  const height = width / cropAspectRatio

  return {
    x: directionX < 0 ? start.x - width : start.x,
    y: directionY < 0 ? start.y - height : start.y,
    width,
    height,
  }
}

export function AvatarCropDialog({
  t,
  source,
  open,
  onCancel,
  onConfirm,
}: {
  t: AppMessages
  source: string | null
  open: boolean
  onCancel: () => void
  onConfirm: (value: string) => void
}) {
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 })
  const [crop, setCrop] = useState({ x: 0, y: 0, width: 0, height: 0 })
  const [interactionMode, setInteractionMode] = useState<
    'draw' | 'move' | 'resize' | null
  >(null)
  const [isSaving, setIsSaving] = useState(false)
  const stageRef = useRef<HTMLDivElement | null>(null)
  const dragStateRef = useRef<{
    pointerId: number
    mode: 'draw' | 'move' | 'resize'
    startPoint: { x: number; y: number }
    originCrop: { x: number; y: number; width: number; height: number }
  } | null>(null)

  const stageSize = useMemo(() => {
    if (!imageSize.width || !imageSize.height) {
      return { width: 0, height: 0 }
    }

    const scale = Math.min(
      maxStageWidth / imageSize.width,
      maxStageHeight / imageSize.height,
    )

    return {
      width: Math.round(imageSize.width * scale),
      height: Math.round(imageSize.height * scale),
    }
  }, [imageSize.height, imageSize.width])

  const hasCrop = crop.width > 0 && crop.height > 0

  const previewStyle = useMemo(() => {
    if (!source || !hasCrop || !stageSize.width || !stageSize.height) {
      return undefined
    }

    const scale = previewWidth / crop.width

    return {
      width: previewWidth,
      height: previewHeight,
      backgroundImage: `url(${source})`,
      backgroundSize: `${stageSize.width * scale}px ${stageSize.height * scale}px`,
      backgroundPosition: `-${crop.x * scale}px -${crop.y * scale}px`,
    }
  }, [crop.width, crop.x, crop.y, hasCrop, source, stageSize.height, stageSize.width])

  useEffect(() => {
    if (!open) {
      return
    }

    setImageSize({ width: 0, height: 0 })
    setCrop({ x: 0, y: 0, width: 0, height: 0 })
    setInteractionMode(null)
    setIsSaving(false)
    dragStateRef.current = null
  }, [open, source])

  if (!source) {
    return null
  }

  function getStagePoint(event: ReactPointerEvent<HTMLDivElement>) {
    const bounds = stageRef.current?.getBoundingClientRect()

    if (!bounds) {
      return { x: 0, y: 0 }
    }

    return {
      x: clamp(event.clientX - bounds.left, 0, bounds.width),
      y: clamp(event.clientY - bounds.top, 0, bounds.height),
    }
  }

  function getHandleRect() {
    return {
      x: crop.x + crop.width - handleHitArea / 2,
      y: crop.y + crop.height - handleHitArea / 2,
      width: handleHitArea,
      height: handleHitArea,
    }
  }

  function handlePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (!stageSize.width || !stageSize.height || isSaving) {
      return
    }

    const point = getStagePoint(event)
    const targetMode =
      hasCrop && pointInRect(point, getHandleRect())
        ? 'resize'
        : hasCrop && pointInRect(point, crop)
          ? 'move'
          : 'draw'

    setInteractionMode(targetMode)
    dragStateRef.current = {
      pointerId: event.pointerId,
      mode: targetMode,
      startPoint: point,
      originCrop: crop,
    }

    if (targetMode === 'draw') {
      setCrop({ x: point.x, y: point.y, width: 0, height: 0 })
    }

    event.currentTarget.setPointerCapture(event.pointerId)
    event.preventDefault()
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const dragState = dragStateRef.current

    if (!dragState || dragState.pointerId !== event.pointerId) {
      return
    }

    const point = getStagePoint(event)

    if (dragState.mode === 'draw') {
      setCrop(createAspectCrop(dragState.startPoint, point, stageSize))
      return
    }

    if (dragState.mode === 'move') {
      setCrop({
        x: clamp(
          dragState.originCrop.x + point.x - dragState.startPoint.x,
          0,
          stageSize.width - dragState.originCrop.width,
        ),
        y: clamp(
          dragState.originCrop.y + point.y - dragState.startPoint.y,
          0,
          stageSize.height - dragState.originCrop.height,
        ),
        width: dragState.originCrop.width,
        height: dragState.originCrop.height,
      })
      return
    }

    const deltaX = point.x - dragState.startPoint.x
    const deltaY = point.y - dragState.startPoint.y
    const widthFromX = dragState.originCrop.width + deltaX
    const widthFromY = dragState.originCrop.width + deltaY * cropAspectRatio
    const maxWidth = Math.min(
      stageSize.width - dragState.originCrop.x,
      (stageSize.height - dragState.originCrop.y) * cropAspectRatio,
    )
    const nextWidth = clamp(
      Math.max(widthFromX, widthFromY),
      minCropWidth,
      maxWidth,
    )

    setCrop({
      x: dragState.originCrop.x,
      y: dragState.originCrop.y,
      width: nextWidth,
      height: nextWidth / cropAspectRatio,
    })
  }

  function handlePointerEnd(event: ReactPointerEvent<HTMLDivElement>) {
    const dragState = dragStateRef.current

    if (!dragState || dragState.pointerId !== event.pointerId) {
      return
    }

    if (dragState.mode === 'draw') {
      setCrop((current) => {
        if (current.width >= minCropWidth) {
          return current
        }

        return { x: 0, y: 0, width: 0, height: 0 }
      })
    }

    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }

    dragStateRef.current = null
    setInteractionMode(null)
  }

  async function handleConfirm() {
    if (!source || !hasCrop || !stageSize.width || !stageSize.height) {
      return
    }

    setIsSaving(true)

    try {
      const scaleX = imageSize.width / stageSize.width
      const scaleY = imageSize.height / stageSize.height
      const croppedAvatar = await cropAvatarDataUrl(source, {
        cropX: Math.round(crop.x * scaleX),
        cropY: Math.round(crop.y * scaleY),
        cropWidth: Math.round(crop.width * scaleX),
        cropHeight: Math.round(crop.height * scaleY),
      })
      onConfirm(croppedAvatar)
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !isSaving) {
          onCancel()
        }
      }}
    >
      <DialogContent
        showCloseButton={!isSaving}
        className="max-h-[calc(100dvh-2rem)] gap-0 overflow-y-auto p-0 sm:max-w-4xl"
        onEscapeKeyDown={(event) => {
          if (isSaving) {
            event.preventDefault()
          }
        }}
        onPointerDownOutside={(event) => event.preventDefault()}
      >
        <DialogHeader className="border-b border-border px-6 py-5 text-left">
          <DialogTitle>{t.cropAvatar}</DialogTitle>
          <DialogDescription>{t.cropAvatarHint}</DialogDescription>
        </DialogHeader>

        <div className="grid gap-6 px-6 py-6 lg:grid-cols-[minmax(0,1fr)_240px]">
          <div className="flex items-center justify-center">
            <div className="relative flex min-h-[420px] w-full items-center justify-center overflow-hidden rounded-[28px] border border-border bg-muted/30 p-4">
              <div
                ref={stageRef}
                className={cn(
                  'relative overflow-hidden rounded-2xl select-none touch-none',
                  interactionMode === 'draw'
                    ? 'cursor-crosshair'
                    : interactionMode === 'move'
                      ? 'cursor-grabbing'
                      : interactionMode === 'resize'
                        ? 'cursor-se-resize'
                        : hasCrop
                          ? 'cursor-default'
                          : 'cursor-crosshair',
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
                  onLoad={(event) => {
                    setImageSize({
                      width: event.currentTarget.naturalWidth,
                      height: event.currentTarget.naturalHeight,
                    })
                  }}
                  draggable={false}
                />

                {hasCrop ? (
                  <>
                    <div
                      className="pointer-events-none absolute left-0 top-0 bg-black/60"
                      style={{ width: stageSize.width, height: crop.y }}
                    />
                    <div
                      className="pointer-events-none absolute left-0 bg-black/60"
                      style={{
                        top: crop.y,
                        width: crop.x,
                        height: crop.height,
                      }}
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
                        'pointer-events-none absolute border-2 border-dashed border-white/95',
                        interactionMode === 'move' && 'shadow-[0_0_0_1px_rgba(255,255,255,0.3)]',
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

          <div className="grid content-start gap-5">
            <div className="grid gap-3">
              <p className="text-sm font-medium">{t.cropPreview}</p>
              <div className="flex items-center justify-center rounded-2xl border border-border bg-muted/35 p-5">
                {previewStyle ? (
                  <div
                    className="overflow-hidden rounded-[22px] border border-border bg-background"
                    style={previewStyle}
                  />
                ) : (
                  <div className="flex h-[135px] w-[108px] items-center justify-center rounded-[22px] border border-dashed border-border bg-background px-3 text-center text-xs text-muted-foreground">
                    {t.cropPreview}
                  </div>
                )}
              </div>
            </div>

            <div className="rounded-2xl border border-border bg-muted/35 p-4 text-sm leading-6 text-muted-foreground">
              {t.cropAvatarGuide}
            </div>
          </div>
        </div>

        <DialogFooter className="border-t border-border px-6 py-5">
          <Button type="button" variant="outline" onClick={onCancel} disabled={isSaving}>
            {t.cancel}
          </Button>
          <Button
            type="button"
            onClick={() => void handleConfirm()}
            disabled={isSaving || !hasCrop}
          >
            {isSaving ? t.saving : t.applyCrop}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
