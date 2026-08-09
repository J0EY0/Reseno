import { useEffect, useMemo, useState } from 'react'

import { cropAvatarDataUrl } from '@/lib/avatar'

import {
  avatarCropAspectRatio,
  type AvatarCropRect,
} from './avatar-crop-geometry'

const maxStageWidth = 520
const maxStageHeight = 420
export const avatarCropPreviewWidth = 108
export const avatarCropPreviewHeight = Math.round(
  avatarCropPreviewWidth / avatarCropAspectRatio,
)

export function useAvatarCrop({
  source,
  open,
  onConfirm,
}: {
  source: string | null
  open: boolean
  onConfirm: (value: string) => void
}) {
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 })
  const [crop, setCrop] = useState<AvatarCropRect>({
    x: 0,
    y: 0,
    width: 0,
    height: 0,
  })
  const [isSaving, setIsSaving] = useState(false)
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

    const scale = avatarCropPreviewWidth / crop.width
    return {
      width: avatarCropPreviewWidth,
      height: avatarCropPreviewHeight,
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
    setIsSaving(false)
  }, [open, source])

  async function confirmCrop() {
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

  return {
    confirmCrop,
    crop,
    hasCrop,
    isSaving,
    onCropChange: setCrop,
    onImageLoad: (width: number, height: number) => setImageSize({ width, height }),
    previewStyle,
    stageSize,
  }
}

export type AvatarCropController = ReturnType<typeof useAvatarCrop>
