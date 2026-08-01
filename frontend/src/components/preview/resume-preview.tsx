import { ImageIcon } from 'lucide-react'
import {
  forwardRef,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent,
  type ReactNode,
} from 'react'

import type { AppMessages } from '@/i18n'
import {
  createContactHref,
  normalizeContactFieldType,
} from '@/lib/contact-links'
import { getInitials, getSectionTitle, hasItemContent } from '@/lib/resume'
import {
  isRichTextEmpty,
  sanitizeRichTextHtml,
  serializeHighlightsToHtml,
} from '@/lib/rich-text'
import { cn } from '@/lib/utils'
import type {
  ResumeBasicInfo,
  ResumeData,
  ResumeDraftDiff,
  ResumeFontFamily,
  ResumeListItemLayout,
  ResumeSection,
  ResumeSectionItem,
  ResumeTemplateDefinition,
  ResumeTemplateImageElement,
  ResumeTemplateLayout,
  ResumeTemplateSettings,
  ResumeTimelineItemLayout,
} from '@/types/resume'

interface ResumePreviewProps {
  t: AppMessages
  resume: ResumeData
  fontFamily: ResumeFontFamily
  fontSize: number
  template: ResumeTemplateDefinition
  variant?: 'default' | 'thumbnail'
  editableTemplateImages?: boolean
  diffs?: ResumeDraftDiff[]
  onMoveTemplateImage?: (
    imageId: string,
    patch: Pick<ResumeTemplateImageElement, 'x' | 'y'>,
  ) => void
}

interface SectionBlockProps {
  section: ResumeSection
  t: AppMessages
  settings: ResumeTemplateSettings
  layout: ResumeTemplateLayout
  isSidebarLayout: boolean
  diff?: ResumeDraftDiff
  itemDiffById?: Map<string, ResumeDraftDiff>
}

interface SectionItemsProps {
  items: ResumeSectionItem[]
  t: AppMessages
  settings: ResumeTemplateSettings
  itemDiffById?: Map<string, ResumeDraftDiff>
}

interface PaginatedResumeSection {
  section: ResumeSection
  items: ResumeSectionItem[]
  showTitle: boolean
}

interface ResumePaginationState {
  pageCount: number
  breakBeforeSectionSpacers: Record<string, number>
}

const fontFamilyMap: Record<ResumeFontFamily, string> = {
  inter:
    '"Inter Variable","Inter","PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Microsoft YaHei",sans-serif',
  serif:
    '"Noto Serif SC Variable","Noto Serif SC","Source Serif 4","Songti SC","STSong","Times New Roman",serif',
  plex:
    '"IBM Plex Sans Variable","IBM Plex Sans","PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Microsoft YaHei",sans-serif',
}

const A4_WIDTH_MM = 210
const A4_HEIGHT_MM = 297
const PAGINATION_TOLERANCE_PX = 8

interface ContactItem {
  id: string
  text: string
  href?: string
}

function getRenderableItems(section: ResumeSection) {
  return section.items.filter(hasItemContent)
}

function createFullPreviewSections(sections: ResumeSection[]) {
  return sections.map((section) => ({
    section,
    items: getRenderableItems(section),
    showTitle: true,
  }))
}

function getPaginationSignature(pagination: ResumePaginationState) {
  const spacers = Object.entries(pagination.breakBeforeSectionSpacers)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([sectionId, spacer]) => `${sectionId}:${Math.round(spacer)}`)
    .join(',')

  return `${pagination.pageCount}|${spacers}`
}

function getOffsetTopWithin(element: HTMLElement, ancestor: HTMLElement) {
  let top = 0
  let current: HTMLElement | null = element

  while (current && current !== ancestor) {
    top += current.offsetTop
    current = current.offsetParent as HTMLElement | null
  }

  return top
}

function parsePixelValue(value: string) {
  const parsed = Number.parseFloat(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function getFallbackName(t: AppMessages) {
  return t.resumePreviewFallbackName
}

function getContactItems(basic: ResumeBasicInfo) {
  const items: ContactItem[] = [
    {
      id: 'phone',
      text: basic.phone.trim(),
      href: createContactHref('phone', basic.phone) ?? undefined,
    },
    {
      id: 'email',
      text: basic.email.trim(),
      href: createContactHref('email', basic.email) ?? undefined,
    },
    { id: 'location', text: basic.location.trim() },
    ...basic.customFields.map((field) => {
      const label = field.label.trim()
      const value = field.value.trim()

      return {
        id: `custom-${field.id}`,
        text: label && value ? `${label}: ${value}` : value || label,
        href: value
          ? createContactHref(normalizeContactFieldType(field.type), value) ??
            undefined
          : undefined,
      }
    }),
  ]

  return items.filter((item) => item.text)
}

function getAvatarBorderRadius(layout: ResumeTemplateLayout) {
  if (layout.avatarShape === 'circle') {
    return '9999px'
  }

  if (layout.avatarShape === 'square') {
    return '4px'
  }

  return '14px'
}

function clampNumber(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

function roundToHalf(value: number) {
  return Math.round(value * 2) / 2
}

function getDiffClassName(diff?: ResumeDraftDiff) {
  return diff ? `resume-diff resume-diff--${diff.kind}` : undefined
}

function getDiffLabel(diff: ResumeDraftDiff | undefined, t: AppMessages) {
  if (!diff) {
    return undefined
  }

  switch (diff.kind) {
    case 'added':
      return t.agentDiffAdded
    case 'deleted':
      return t.agentDiffDeleted
    case 'moved':
      return t.agentDiffMoved
    case 'modified':
      return t.agentDiffModified
  }
}

function createDiffLookup(diffs: ResumeDraftDiff[]) {
  const sectionDiffById = new Map<string, ResumeDraftDiff>()
  const itemDiffById = new Map<string, ResumeDraftDiff>()
  let summaryDiff: ResumeDraftDiff | undefined

  diffs.forEach((diff) => {
    if (diff.path === 'basic.summary') {
      summaryDiff = diff
    }

    if (diff.sectionId && !diff.itemId) {
      sectionDiffById.set(diff.sectionId, diff)
    }

    if (diff.itemId) {
      itemDiffById.set(diff.itemId, diff)
    }
  })

  return { sectionDiffById, itemDiffById, summaryDiff }
}

function getAvatarPlaceholderLabel(src: string, fallbackLabel: string) {
  if (!src.startsWith('data:image/svg+xml')) {
    return null
  }

  try {
    const decoded = decodeURIComponent(src)

    if (!decoded.includes('data-resumate-avatar-placeholder="true"')) {
      return null
    }

    return decoded.match(/data-placeholder-label="([^"]*)"/)?.[1] ?? fallbackLabel
  } catch {
    return null
  }
}

function AvatarPreview({
  basic,
  layout,
  t,
  className,
  imageClassName,
}: {
  basic: ResumeBasicInfo
  layout: ResumeTemplateLayout
  t: AppMessages
  className: string
  imageClassName?: string
}) {
  if (!basic.avatar.trim()) {
    return null
  }

  const placeholderLabel = getAvatarPlaceholderLabel(
    basic.avatar,
    t.resumePreviewAvatarPlaceholder,
  )
  const isPlaceholder = Boolean(placeholderLabel)
  const placeholderBorderColor =
    layout.avatarBorderWidth > 0
      ? layout.avatarBorderColor
      : layout.basicInfo === 'sidebar'
        ? 'rgba(255,255,255,0.58)'
        : 'rgba(113,113,122,0.36)'
  const placeholderTextColor =
    layout.basicInfo === 'sidebar' ? 'rgba(255,255,255,0.78)' : '#71717a'
  const placeholderFontSize = `${Math.max(
    14,
    Math.min(28, layout.avatarWidth * 0.9),
  )}px`

  return (
    <div
      data-avatar-frame="true"
      data-avatar-initials={getInitials(basic.name)}
      className={cn(
        'flex items-center justify-center overflow-hidden bg-transparent font-semibold',
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
          alt={basic.name}
          className={cn('block size-full object-cover object-center', imageClassName)}
          crossOrigin="anonymous"
          loading="eager"
          decoding="sync"
          draggable={false}
        />
      )}
    </div>
  )
}

function isDefaultTemplateImagePlaceholder(image: ResumeTemplateImageElement) {
  return !image.src && /^Image \d+$/.test(image.name)
}

function getSafeTemplateImageFrame(
  image: ResumeTemplateImageElement,
  layout: ResumeTemplateLayout,
) {
  const isLegacyTopLeftDefault =
    isDefaultTemplateImagePlaceholder(image) && image.x <= 16 && image.y <= 20

  if (!isLegacyTopLeftDefault || layout.avatarPosition === 'right') {
    return image
  }

  return {
    ...image,
    x: 166,
    y: 18,
  }
}

function TemplateImages({
  images,
  layout,
  editable = false,
  onMoveImage,
}: {
  images?: ResumeTemplateImageElement[]
  layout: ResumeTemplateLayout
  editable?: boolean
  onMoveImage?: (
    imageId: string,
    patch: Pick<ResumeTemplateImageElement, 'x' | 'y'>,
  ) => void
}) {
  const dragStateRef = useRef<{
    imageId: string
    pointerId: number
    startClientX: number
    startClientY: number
    startX: number
    startY: number
    width: number
    height: number
    pxPerMm: number
  } | null>(null)
  const visibleImages = (images ?? []).filter((image) => image.visible)

  if (visibleImages.length === 0) {
    return null
  }

  function handlePointerDown(
    event: PointerEvent<HTMLDivElement>,
    frame: ResumeTemplateImageElement,
  ) {
    if (!editable || !onMoveImage || event.button !== 0) {
      return
    }

    const pageElement = event.currentTarget.closest(
      '[data-export-root="resume-page"]',
    ) as HTMLElement | null
    const pageRect = pageElement?.getBoundingClientRect()
    const pxPerMm =
      pageRect && pageRect.width > 0
        ? pageRect.width / 210
        : event.currentTarget.getBoundingClientRect().width / frame.width

    event.preventDefault()
    event.stopPropagation()
    event.currentTarget.setPointerCapture(event.pointerId)

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
    }
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>) {
    const dragState = dragStateRef.current

    if (!dragState || !onMoveImage || dragState.pointerId !== event.pointerId) {
      return
    }

    event.preventDefault()

    const nextX = clampNumber(
      roundToHalf(
        dragState.startX +
          (event.clientX - dragState.startClientX) / dragState.pxPerMm,
      ),
      0,
      Math.max(0, 210 - dragState.width),
    )
    const nextY = clampNumber(
      roundToHalf(
        dragState.startY +
          (event.clientY - dragState.startClientY) / dragState.pxPerMm,
      ),
      0,
      Math.max(0, 297 - dragState.height),
    )

    onMoveImage(dragState.imageId, { x: nextX, y: nextY })
  }

  function handlePointerUp(event: PointerEvent<HTMLDivElement>) {
    const dragState = dragStateRef.current

    if (!dragState || dragState.pointerId !== event.pointerId) {
      return
    }

    event.currentTarget.releasePointerCapture(event.pointerId)
    dragStateRef.current = null
  }

  return (
    <div
      className={cn(
        'pointer-events-none absolute inset-0',
        editable ? 'z-20' : 'z-0',
      )}
    >
      {visibleImages.map((image) => {
        const frame = getSafeTemplateImageFrame(image, layout)

        return (
          <div
            key={image.id}
            className={cn(
              'absolute flex min-h-6 min-w-6 items-center justify-center overflow-hidden text-center text-[9px] font-medium text-slate-400',
              !frame.src && 'bg-white/10',
              editable &&
                'pointer-events-auto cursor-grab touch-none transition-[box-shadow,outline-color] active:cursor-grabbing hover:shadow-sm',
            )}
            style={{
              left: `${frame.x}mm`,
              top: `${frame.y}mm`,
              width: `${frame.width}mm`,
              height: `${frame.height}mm`,
              opacity: frame.opacity,
              borderWidth: `${frame.borderWidth}px`,
              borderColor: frame.borderColor,
              borderStyle: frame.borderWidth > 0 ? 'solid' : 'none',
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
                <span className="max-w-full truncate leading-none text-slate-500/80">
                  {frame.name}
                </span>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function ContactLine({
  items,
  enableLinks,
  className,
}: {
  items: ContactItem[]
  enableLinks: boolean
  className?: string
}) {
  if (items.length === 0) {
    return null
  }

  return (
    <div className={cn('flex flex-wrap justify-center gap-x-3 gap-y-1', className)}>
      {items.map((item, index) => (
        <span key={item.id}>
          <ContactItemText item={item} enableLink={enableLinks} />
          {index < items.length - 1 ? (
            <span className="resume-tone-subtle ml-3">|</span>
          ) : null}
        </span>
      ))}
    </div>
  )
}

function ContactItemText({
  item,
  enableLink,
}: {
  item: ContactItem
  enableLink: boolean
}) {
  if (!enableLink || !item.href) {
    return <span>{item.text}</span>
  }

  const opensNewTab =
    item.href.startsWith('http://') || item.href.startsWith('https://')

  return (
    <a
      href={item.href}
      className="text-inherit no-underline hover:underline"
      target={opensNewTab ? '_blank' : undefined}
      rel={opensNewTab ? 'noreferrer noopener' : undefined}
    >
      {item.text}
    </a>
  )
}

function StandardBasicInfo({
  t,
  basic,
  settings,
  layout,
  summaryDiff,
  enableContactLinks,
}: {
  t: AppMessages
  basic: ResumeBasicInfo
  settings: ResumeTemplateSettings
  layout: ResumeTemplateLayout
  summaryDiff?: ResumeDraftDiff
  enableContactLinks: boolean
}) {
  const isProfile = layout.basicInfo === 'profile'
  const isLeftAligned = layout.basicInfo === 'left'
  const isSplit = layout.basicInfo === 'split'
  const avatarPosition = layout.avatarPosition
  const hasAvatar = avatarPosition !== 'none' && Boolean(basic.avatar.trim())
  const shouldFloatSideAvatar =
    hasAvatar && !isProfile && avatarPosition !== 'center'
  const contactItems = getContactItems(basic)
  const avatar = hasAvatar ? (
    <AvatarPreview
      basic={basic}
      layout={layout}
      t={t}
      className={cn(
        shouldFloatSideAvatar &&
          (avatarPosition === 'left'
            ? 'absolute left-0 top-0 z-10'
            : 'absolute right-0 top-0 z-10'),
        isProfile && avatarPosition === 'center'
          ? 'size-[112px]'
          : layout.avatarShape === 'circle'
            ? 'size-[108px]'
          : isProfile
            ? 'size-[108px]'
            : 'h-[120px] w-[96px]',
      )}
    />
  ) : null
  const identityContent = (
    <>
      <h1
        className="font-extrabold tracking-[-0.04em]"
        style={{
          color: isProfile ? settings.bodyColor : settings.headingColor,
          fontSize: `${settings.nameScale}em`,
        }}
      >
        {basic.name || getFallbackName(t)}
      </h1>
      {basic.headline ? (
        <p
          className={cn(
            'resume-tone-muted mt-2 font-medium',
            isProfile && 'tracking-[0.08em]',
          )}
          style={{ fontSize: `${Math.max(0.85, settings.bodyScale)}em` }}
        >
          {basic.headline}
        </p>
      ) : null}
    </>
  )
  const contactContent = (
    <ContactLine
      items={contactItems}
      enableLinks={enableContactLinks}
      className="resume-tone-body mt-3"
    />
  )
  const infoContent = (
    <>
      {identityContent}
      {contactContent}
    </>
  )

  return (
    <header
      className={cn(
        'relative grid gap-4',
        isProfile && 'overflow-hidden rounded-2xl px-5 py-5',
      )}
      style={
        isProfile
          ? {
              background: `linear-gradient(180deg, ${settings.dividerColor}18, transparent 68%)`,
            }
          : undefined
      }
    >
      {avatar && avatarPosition === 'center' ? (
        <div className="grid justify-items-center gap-3 text-center">
          {avatar}
          <div>{infoContent}</div>
        </div>
      ) : shouldFloatSideAvatar ? (
        <>
          {avatar}
          <div className="mx-auto text-center">{infoContent}</div>
        </>
      ) : avatar ? (
        <div
          className={cn(
            'grid items-start gap-5',
            avatarPosition === 'left'
              ? 'grid-cols-[auto_minmax(0,1fr)]'
              : 'grid-cols-[minmax(0,1fr)_auto]',
          )}
        >
          {avatarPosition === 'left' ? avatar : null}
          <div
            className={cn(
              avatarPosition === 'left' ? 'text-left' : 'mx-auto text-center',
            )}
          >
            {infoContent}
          </div>
          {avatarPosition !== 'left' ? avatar : null}
        </div>
      ) : isSplit ? (
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,0.85fr)] items-end gap-8">
          <div className="text-left">{identityContent}</div>
          <div className="min-w-0">
            <ContactLine
              items={contactItems}
              enableLinks={enableContactLinks}
              className="resume-tone-body mt-0 justify-end text-right"
            />
          </div>
        </div>
      ) : isLeftAligned ? (
        <div className="text-left">{infoContent}</div>
      ) : (
        <div className="mx-auto text-center">{infoContent}</div>
      )}

      {basic.summary ? (
        <p
          className={cn('resume-tone-body text-left', getDiffClassName(summaryDiff))}
          data-resume-diff-kind={summaryDiff?.kind}
          data-resume-diff-label={getDiffLabel(summaryDiff, t)}
          style={{
            fontSize: `${settings.bodyScale}em`,
            lineHeight: settings.bodyLineHeight,
          }}
        >
          {basic.summary}
        </p>
      ) : null}
    </header>
  )
}

function SidebarBasicInfo({
  t,
  basic,
  settings,
  layout,
  summaryDiff,
  enableContactLinks,
}: {
  t: AppMessages
  basic: ResumeBasicInfo
  settings: ResumeTemplateSettings
  layout: ResumeTemplateLayout
  summaryDiff?: ResumeDraftDiff
  enableContactLinks: boolean
}) {
  const contactItems = getContactItems(basic)
  const avatar =
    layout.avatarPosition === 'none' ? null : (
      <AvatarPreview
        basic={basic}
        layout={layout}
        t={t}
        className={cn(
          'mx-auto bg-white/10',
          layout.avatarShape === 'circle' ? 'size-[108px]' : 'h-[118px] w-[96px]',
        )}
      />
    )

  return (
    <aside
      className="flex min-h-[297mm] flex-col gap-8 px-7 py-10 text-white"
      style={{ backgroundColor: settings.surfaceColor }}
    >
      {avatar}

      <div className="grid gap-2">
        <h1
          className="font-semibold tracking-[-0.03em]"
          style={{ fontSize: `${settings.nameScale}em` }}
        >
          {basic.name || getFallbackName(t)}
        </h1>
        {basic.headline ? (
          <p className="text-white/75" style={{ fontSize: `${settings.bodyScale}em` }}>
            {basic.headline}
          </p>
        ) : null}
      </div>

      {contactItems.length > 0 ? (
        <div className="grid gap-2">
          <p className="font-semibold" style={{ fontSize: `${settings.sectionTitleScale}em` }}>
            {t.resumePreviewContactTitle}
          </p>
          <div
            className="grid gap-1.5 text-white/90"
            style={{
              fontSize: `${settings.metaScale}em`,
              lineHeight: settings.bodyLineHeight,
            }}
          >
            {contactItems.map((item) => (
              <ContactItemText
                key={item.id}
                item={item}
                enableLink={enableContactLinks}
              />
            ))}
          </div>
        </div>
      ) : null}

      {basic.summary ? (
        <div className="grid gap-2">
          <p className="font-semibold" style={{ fontSize: `${settings.sectionTitleScale}em` }}>
            {t.resumePreviewSummaryTitle}
          </p>
          <p
            className={cn('text-white/80', getDiffClassName(summaryDiff))}
            data-resume-diff-kind={summaryDiff?.kind}
            data-resume-diff-label={getDiffLabel(summaryDiff, t)}
            style={{
              fontSize: `${settings.bodyScale}em`,
              lineHeight: settings.bodyLineHeight,
            }}
          >
            {basic.summary}
          </p>
        </div>
      ) : null}
    </aside>
  )
}

function TimelineItem({
  item,
  t,
  settings,
  diff,
  layout,
}: {
  item: ResumeSectionItem
  t: AppMessages
  settings: ResumeTemplateSettings
  diff?: ResumeDraftDiff
  layout: ResumeTimelineItemLayout
}) {
  const highlightsHtml = serializeHighlightsToHtml(item.highlights)
  const title = (
    <h3
      className="min-w-0 break-words font-extrabold"
      style={{
        color: settings.bodyColor,
        fontSize: `${settings.itemTitleScale}em`,
      }}
    >
      {item.title}
    </h3>
  )
  const subtitle = item.subtitle ? (
    <p
      className={cn(
        'min-w-0 break-words font-medium',
        layout === 'split' && 'mt-1',
      )}
      style={{
        color: settings.bodyColor,
        fontSize: `${settings.bodyScale}em`,
      }}
    >
      {item.subtitle}
    </p>
  ) : null
  const metadata = [item.meta, item.period].filter(Boolean)

  let heading: ReactNode

  if (layout === 'stacked') {
    heading = (
      <div className="grid gap-1">
        {title}
        {subtitle}
        {metadata.length > 0 ? (
          <div
            className="resume-tone-muted flex flex-wrap gap-x-3 gap-y-1"
            style={{ fontSize: `${settings.metaScale}em` }}
          >
            {metadata.map((value, index) => (
              <span key={`${value}-${index}`}>{value}</span>
            ))}
          </div>
        ) : null}
      </div>
    )
  } else if (layout === 'compact') {
    heading = (
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4 gap-y-1">
        {title}
        {item.period ? (
          <span
            className="resume-tone-muted col-start-2 row-start-1 whitespace-nowrap text-right"
            style={{ fontSize: `${settings.metaScale}em` }}
          >
            {item.period}
          </span>
        ) : null}
        {item.subtitle ? (
          <div className="col-start-1 row-start-2">{subtitle}</div>
        ) : null}
        {item.meta ? (
          <span
            className="resume-tone-muted col-start-2 row-start-2 whitespace-nowrap text-right"
            style={{ fontSize: `${settings.metaScale}em` }}
          >
            {item.meta}
          </span>
        ) : null}
      </div>
    )
  } else {
    heading = (
      <div className="flex items-start justify-between gap-4 max-md:flex-col">
        <div className="min-w-0">
          {title}
          {subtitle}
        </div>
        {metadata.length > 0 ? (
          <div
            className="resume-tone-muted grid min-w-[170px] gap-1 text-right max-md:min-w-0 max-md:text-left"
            style={{ fontSize: `${settings.metaScale}em` }}
          >
            {item.meta ? <span>{item.meta}</span> : null}
            {item.period ? <span>{item.period}</span> : null}
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <article
      className={cn('resume-item grid gap-2', getDiffClassName(diff))}
      data-resume-item-id={item.id}
      data-resume-diff-kind={diff?.kind}
      data-resume-diff-label={getDiffLabel(diff, t)}
    >
      {heading}

      {item.description ? (
        <p
          className="resume-tone-body"
          style={{
            fontSize: `${settings.bodyScale}em`,
            lineHeight: settings.bodyLineHeight,
          }}
        >
          {item.description}
        </p>
      ) : null}

      {!isRichTextEmpty(highlightsHtml) ? (
        <div
          className="resume-rich-text resume-tone-body"
          style={{
            fontSize: `${settings.bodyScale}em`,
            lineHeight: settings.bodyLineHeight,
          }}
          dangerouslySetInnerHTML={{
            __html: sanitizeRichTextHtml(highlightsHtml),
          }}
        />
      ) : null}
    </article>
  )
}

function TimelineItems({
  items,
  t,
  settings,
  itemDiffById,
  layout,
}: SectionItemsProps & { layout: ResumeTimelineItemLayout }) {
  return (
    <div
      className="grid"
      data-resume-items-list="true"
      style={{ gap: `${settings.itemGap}em` }}
    >
      {items.map((item) => (
        <TimelineItem
          key={item.id}
          item={item}
          t={t}
          settings={settings}
          diff={itemDiffById?.get(item.id)}
          layout={layout}
        />
      ))}
    </div>
  )
}

function ListItem({
  item,
  t,
  settings,
  diff,
  layout,
}: {
  item: ResumeSectionItem
  t: AppMessages
  settings: ResumeTemplateSettings
  diff?: ResumeDraftDiff
  layout: ResumeListItemLayout
}) {
  const highlightsHtml = serializeHighlightsToHtml(item.highlights)
  const hasDetails =
    Boolean(item.description) || !isRichTextEmpty(highlightsHtml)

  return (
    <li
      className={cn(
        'resume-item min-w-0',
        layout === 'inline' &&
          'flex items-start gap-1.5 before:shrink-0 before:content-["•"]',
        layout === 'inline' && (hasDetails ? 'basis-full' : 'flex-none'),
        getDiffClassName(diff),
      )}
      data-resume-item-id={item.id}
      data-resume-diff-kind={diff?.kind}
      data-resume-diff-label={getDiffLabel(diff, t)}
    >
      <strong style={{ color: settings.bodyColor }}>{item.title}</strong>
      {item.subtitle ? <span>：{item.subtitle}</span> : null}
      {item.meta || item.period ? (
        <span className="resume-tone-muted ml-2">
          {[item.meta, item.period].filter(Boolean).join(' · ')}
        </span>
      ) : null}
      {item.description ? (
        <p className="resume-tone-muted mt-1">{item.description}</p>
      ) : null}
      {!isRichTextEmpty(highlightsHtml) ? (
        <div
          className="resume-rich-text mt-1"
          dangerouslySetInnerHTML={{
            __html: sanitizeRichTextHtml(highlightsHtml),
          }}
        />
      ) : null}
    </li>
  )
}

function ListItems({
  items,
  t,
  settings,
  itemDiffById,
  layout,
}: SectionItemsProps & { layout: ResumeListItemLayout }) {
  return (
    <ul
      className={cn(
        'resume-tone-body',
        layout === 'list' && 'grid list-disc pl-5',
        layout === 'columns' &&
          'grid grid-cols-2 gap-x-6 list-disc pl-5',
        layout === 'inline' && 'flex flex-wrap items-start gap-x-4 pl-0',
      )}
      data-resume-items-list="true"
      style={{
        gap: `${Math.max(0.35, settings.itemGap / 2)}em`,
        fontSize: `${settings.bodyScale}em`,
        lineHeight: settings.bodyLineHeight,
      }}
    >
      {items.map((item) => (
        <ListItem
          key={item.id}
          item={item}
          t={t}
          settings={settings}
          diff={itemDiffById?.get(item.id)}
          layout={layout}
        />
      ))}
    </ul>
  )
}

function SectionItems({
  section,
  t,
  settings,
  layout,
  items,
  itemDiffById,
}: {
  section: ResumeSection
  t: AppMessages
  settings: ResumeTemplateSettings
  layout: ResumeTemplateLayout
  items?: ResumeSectionItem[]
  itemDiffById?: Map<string, ResumeDraftDiff>
}) {
  const visibleItems = items ?? getRenderableItems(section)

  if (section.layout === 'list') {
    return (
      <ListItems
        items={visibleItems}
        t={t}
        settings={settings}
        itemDiffById={itemDiffById}
        layout={layout.listItemLayout}
      />
    )
  }

  return (
    <TimelineItems
      items={visibleItems}
      t={t}
      settings={settings}
      itemDiffById={itemDiffById}
      layout={layout.timelineItemLayout}
    />
  )
}

function RuledSectionTitle({
  children,
  settings,
}: {
  children: ReactNode
  settings: ResumeTemplateSettings
}) {
  return (
    <div className="flex items-center gap-4">
      <h2
        className="shrink-0 font-extrabold"
        style={{
          color: settings.headingColor,
          fontSize: `${settings.sectionTitleScale}em`,
        }}
      >
        {children}
      </h2>
      <div
        className="flex-1"
        style={{
          height: `${settings.dividerThickness}px`,
          backgroundColor: settings.dividerColor,
        }}
      />
    </div>
  )
}

function AccentSectionTitle({
  children,
  settings,
  isSidebarLayout,
}: {
  children: ReactNode
  settings: ResumeTemplateSettings
  isSidebarLayout: boolean
}) {
  if (isSidebarLayout) {
    return <RuledSectionTitle settings={settings}>{children}</RuledSectionTitle>
  }

  return (
    <div className="relative flex items-center justify-center">
      <div
        className="absolute inset-x-0 top-1/2"
        style={{
          height: `${settings.dividerThickness}px`,
          backgroundColor: settings.dividerColor,
        }}
      />
      <h2
        className="relative px-4 text-center font-extrabold tracking-[0.18em]"
        style={{
          color: settings.headingColor,
          backgroundColor: settings.pageBackground,
          fontSize: `${settings.sectionTitleScale}em`,
        }}
      >
        {children}
      </h2>
    </div>
  )
}

function SectionBlock({
  section,
  t,
  settings,
  layout,
  isSidebarLayout,
  items,
  showTitle = true,
  breakBeforeOffset = 0,
  diff,
  itemDiffById,
}: SectionBlockProps & {
  items?: ResumeSectionItem[]
  showTitle?: boolean
  breakBeforeOffset?: number
}) {
  const title = getSectionTitle(section, t)
  const visibleItems = items ?? getRenderableItems(section)
  const sectionStyle = breakBeforeOffset > 0 ? { marginTop: breakBeforeOffset } : undefined

  if (layout.section === 'boxed') {
    return (
      <section
        className={cn(
          'resume-section relative overflow-hidden border',
          getDiffClassName(diff),
        )}
        data-resume-section-id={section.id}
        data-resume-diff-kind={diff?.kind}
        style={{ ...sectionStyle, borderColor: settings.dividerColor }}
      >
        {showTitle ? (
          <div
            className="resume-section-header border-b px-4 py-2"
            data-resume-section-header="true"
            style={{
              backgroundColor: settings.surfaceColor,
              borderColor: settings.dividerColor,
            }}
          >
            <h2
              className="font-extrabold"
              style={{
                color: settings.headingColor,
                fontSize: `${settings.sectionTitleScale}em`,
              }}
            >
              {title}
            </h2>
          </div>
        ) : null}
        <div className="p-4">
          <SectionItems
            section={section}
            t={t}
            settings={settings}
            layout={layout}
            items={visibleItems}
            itemDiffById={itemDiffById}
          />
        </div>
      </section>
    )
  }

  if (layout.section === 'band') {
    return (
      <section
        className={cn('resume-section relative', getDiffClassName(diff))}
        data-resume-section-id={section.id}
        data-resume-diff-kind={diff?.kind}
        style={sectionStyle}
      >
        {showTitle ? (
          <div
            className="resume-section-header rounded-sm px-3 py-1.5"
            data-resume-section-header="true"
            style={{ backgroundColor: settings.surfaceColor }}
          >
            <h2
              className="font-extrabold"
              style={{
                color: settings.headingColor,
                fontSize: `${settings.sectionTitleScale}em`,
              }}
            >
              {title}
            </h2>
          </div>
        ) : null}
        <div className={showTitle ? 'mt-3' : undefined}>
          <SectionItems
            section={section}
            t={t}
            settings={settings}
            layout={layout}
            items={visibleItems}
            itemDiffById={itemDiffById}
          />
        </div>
      </section>
    )
  }

  return (
    <section
      className={cn('resume-section relative', getDiffClassName(diff))}
      data-resume-section-id={section.id}
      data-resume-diff-kind={diff?.kind}
      style={sectionStyle}
    >
      {showTitle ? (
        <div
          className="resume-section-header"
          data-resume-section-header="true"
        >
          {layout.section === 'plain' ? (
            <h2
              className="font-extrabold"
              style={{
                color: settings.headingColor,
                fontSize: `${settings.sectionTitleScale}em`,
              }}
            >
              {title}
            </h2>
          ) : layout.section === 'accent' ? (
            <AccentSectionTitle settings={settings} isSidebarLayout={isSidebarLayout}>
              {title}
            </AccentSectionTitle>
          ) : (
            <RuledSectionTitle settings={settings}>{title}</RuledSectionTitle>
          )}
        </div>
      ) : null}
      <div className={showTitle ? 'mt-3' : undefined}>
        <SectionItems
          section={section}
          t={t}
          settings={settings}
          layout={layout}
          items={visibleItems}
          itemDiffById={itemDiffById}
        />
      </div>
    </section>
  )
}

function SectionsList({
  sections,
  t,
  settings,
  layout,
  isSidebarLayout,
  className,
  breakBeforeSectionSpacers,
  sectionDiffById,
  itemDiffById,
}: {
  sections: PaginatedResumeSection[]
  t: AppMessages
  settings: ResumeTemplateSettings
  layout: ResumeTemplateLayout
  isSidebarLayout: boolean
  className?: string
  breakBeforeSectionSpacers?: Record<string, number>
  sectionDiffById?: Map<string, ResumeDraftDiff>
  itemDiffById?: Map<string, ResumeDraftDiff>
}) {
  return (
    <div
      className={cn('grid', className)}
      data-resume-sections-list="true"
      style={{ gap: `${settings.sectionGap}em` }}
    >
      {sections.map((section) => (
        <SectionBlock
          key={`${section.section.id}-${section.showTitle ? 'title' : 'continue'}-${section.items
            .map((item) => item.id)
            .join('-')}`}
          section={section.section}
          items={section.items}
          showTitle={section.showTitle}
          breakBeforeOffset={
            breakBeforeSectionSpacers?.[section.section.id] ?? 0
          }
          t={t}
          settings={settings}
          layout={layout}
          isSidebarLayout={isSidebarLayout}
          diff={sectionDiffById?.get(section.section.id)}
          itemDiffById={itemDiffById}
        />
      ))}
    </div>
  )
}

function measureSectionBlocks(
  element: HTMLElement,
  sections: ResumeSection[],
) {
  const measures = new Map<
    string,
    {
      headerBlockHeight: number
    }
  >()

  sections.forEach((section) => {
    const sectionElement = element.querySelector<HTMLElement>(
      `[data-resume-section-id="${section.id}"]`,
    )

    if (!sectionElement) {
      return
    }

    const firstItemElement = sectionElement.querySelector<HTMLElement>(
      '[data-resume-item-id]',
    )
    const headerBlockHeight = firstItemElement
      ? getOffsetTopWithin(firstItemElement, sectionElement)
      : sectionElement.offsetHeight

    measures.set(section.id, {
      headerBlockHeight,
    })
  })

  return measures
}

function calculateResumePagination({
  element,
  sections,
  contentWidthMm,
  pageHeightMm,
}: {
  element: HTMLElement
  sections: ResumeSection[]
  contentWidthMm: number
  pageHeightMm: number
}) {
  const layoutWidth = element.offsetWidth || element.clientWidth
  const pxPerMm = layoutWidth > 0 ? layoutWidth / contentWidthMm : 1
  const pageHeight =
    layoutWidth > 0
      ? Math.round(pageHeightMm * pxPerMm)
      : element.scrollHeight || 1
  const contentElement = element.querySelector<HTMLElement>(
    '[data-resume-flow-content="true"]',
  )
  const sectionMeasures = measureSectionBlocks(element, sections)
  const breakBeforeSectionSpacers: Record<string, number> = {}

  sections.forEach((section) => {
    const items = getRenderableItems(section)
    const measure = sectionMeasures.get(section.id)
    const sectionElement = element.querySelector<HTMLElement>(
      `[data-resume-section-id="${section.id}"]`,
    )

    if (items.length === 0 || !measure || !sectionElement) {
      return
    }

    const sectionStyle = window.getComputedStyle(sectionElement)
    const currentSpacer = parsePixelValue(sectionStyle.marginTop)
    const sectionTop = getOffsetTopWithin(sectionElement, element) - currentSpacer
    const offsetWithinPage = sectionTop % pageHeight
    const remainingOnPage = pageHeight - offsetWithinPage
    const followingContentVisibleOnPage = remainingOnPage - measure.headerBlockHeight

    if (
      offsetWithinPage > PAGINATION_TOLERANCE_PX &&
      followingContentVisibleOnPage <= PAGINATION_TOLERANCE_PX
    ) {
      const spacer = remainingOnPage

      breakBeforeSectionSpacers[section.id] = spacer
    }
  })

  const measuredContentHeight = contentElement
    ? contentElement.offsetTop + contentElement.offsetHeight
    : element.scrollHeight
  const addedSpacerDelta = Object.entries(breakBeforeSectionSpacers).reduce(
    (total, [sectionId, spacer]) => {
      const sectionElement = element.querySelector<HTMLElement>(
        `[data-resume-section-id="${sectionId}"]`,
      )
      const currentSpacer = sectionElement
        ? parsePixelValue(window.getComputedStyle(sectionElement).marginTop)
        : 0

      return total + Math.max(0, spacer - currentSpacer)
    },
    0,
  )
  const pageCount = Math.max(
    1,
    Math.ceil(
      Math.max(
        measuredContentHeight + addedSpacerDelta - PAGINATION_TOLERANCE_PX,
        0,
      ) / pageHeight,
    ),
  )

  return {
    pageCount,
    breakBeforeSectionSpacers,
  }
}

export const ResumePreview = forwardRef<HTMLElement, ResumePreviewProps>(function ResumePreview({
  t,
  resume,
  fontFamily,
  fontSize,
  template,
  variant = 'default',
  editableTemplateImages = false,
  diffs = [],
  onMoveTemplateImage,
}, ref) {
  const visibleSections = useMemo(
    () => resume.sections.filter((section) => section.items.some(hasItemContent)),
    [resume.sections],
  )
  const settings = template.settings
  const layout = template.layout
  const isSidebarLayout = layout.basicInfo === 'sidebar'
  // Gallery thumbnails live inside a card link. Rendering contact anchors there
  // would create invalid nested links, while full previews and exports stay interactive.
  const enableContactLinks = variant !== 'thumbnail'
  const standardContentWidthMm = A4_WIDTH_MM - settings.pagePaddingX * 2
  const standardContentHeightMm =
    A4_HEIGHT_MM - settings.pagePaddingTop - settings.pagePaddingBottom
  const fullPreviewSections = useMemo(
    () => createFullPreviewSections(visibleSections),
    [visibleSections],
  )
  const diffLookup = useMemo(() => createDiffLookup(diffs), [diffs])
  const measureRef = useRef<HTMLDivElement | null>(null)
  const [pagination, setPagination] = useState<ResumePaginationState>({
    pageCount: 1,
    breakBeforeSectionSpacers: {},
  })

  const pageStyle: CSSProperties = {
    fontFamily: fontFamilyMap[fontFamily],
    fontSize: `${fontSize}px`,
    paddingTop: isSidebarLayout ? 0 : `${settings.pagePaddingTop}mm`,
    paddingRight: isSidebarLayout ? 0 : `${settings.pagePaddingX}mm`,
    paddingBottom: isSidebarLayout ? 0 : `${settings.pagePaddingBottom}mm`,
    paddingLeft: isSidebarLayout ? 0 : `${settings.pagePaddingX}mm`,
    backgroundColor: settings.pageBackground,
    color: settings.bodyColor,
    ['--resume-page-bg' as string]: settings.pageBackground,
    ['--resume-surface-color' as string]: settings.surfaceColor,
    ['--resume-heading-color' as string]: settings.headingColor,
    ['--resume-body-color' as string]: settings.bodyColor,
    ['--resume-muted-color' as string]: settings.mutedColor,
    ['--resume-divider-color' as string]: settings.dividerColor,
  }
  const contentFlowStyle: CSSProperties = {
    fontFamily: fontFamilyMap[fontFamily],
    fontSize: `${fontSize}px`,
    width: `${standardContentWidthMm}mm`,
    backgroundColor: settings.pageBackground,
    color: settings.bodyColor,
    ['--resume-page-bg' as string]: settings.pageBackground,
    ['--resume-surface-color' as string]: settings.surfaceColor,
    ['--resume-heading-color' as string]: settings.headingColor,
    ['--resume-body-color' as string]: settings.bodyColor,
    ['--resume-muted-color' as string]: settings.mutedColor,
    ['--resume-divider-color' as string]: settings.dividerColor,
  }

  const pageClassName = cn(
    'resume-page',
    isSidebarLayout && 'resume-page--sidebar',
    variant === 'thumbnail' && 'resume-page--thumbnail',
    !isSidebarLayout && template.preset === 'modern' && 'resume-page--modern',
    !isSidebarLayout && template.preset === 'compact' && 'resume-page--compact',
  )

  useLayoutEffect(() => {
    if (variant === 'thumbnail') {
      return
    }

    const element = measureRef.current

    if (!element) {
      return
    }

    let animationFrameId = 0

    const syncPages = () => {
      animationFrameId = 0

      const nextPagination = calculateResumePagination({
        element,
        sections: visibleSections,
        contentWidthMm: isSidebarLayout ? A4_WIDTH_MM : standardContentWidthMm,
        pageHeightMm: isSidebarLayout ? A4_HEIGHT_MM : standardContentHeightMm,
      })
      const nextSignature = getPaginationSignature(nextPagination)

      setPagination((currentPagination) =>
        getPaginationSignature(currentPagination) === nextSignature
          ? currentPagination
          : nextPagination,
      )
    }

    const scheduleSync = () => {
      if (animationFrameId) {
        window.cancelAnimationFrame(animationFrameId)
      }

      animationFrameId = window.requestAnimationFrame(syncPages)
    }

    scheduleSync()

    if (typeof ResizeObserver === 'undefined') {
      return () => {
        if (animationFrameId) {
          window.cancelAnimationFrame(animationFrameId)
        }
      }
    }

    const resizeObserver = new ResizeObserver(scheduleSync)
    resizeObserver.observe(element)

    return () => {
      if (animationFrameId) {
        window.cancelAnimationFrame(animationFrameId)
      }

      resizeObserver.disconnect()
    }
  }, [
    fontFamily,
    fontSize,
    isSidebarLayout,
    resume,
    settings,
    standardContentHeightMm,
    standardContentWidthMm,
    t,
    template,
    variant,
    visibleSections,
  ])

  function renderStandardFlowContent(
    pageSections = fullPreviewSections,
    includeBasicInfo = true,
    breakBeforeSectionSpacers?: Record<string, number>,
  ) {
    return (
      <div className="relative z-10" data-resume-flow-content="true">
        {includeBasicInfo ? (
          <StandardBasicInfo
            t={t}
            basic={resume.basic}
            settings={settings}
            layout={layout}
            summaryDiff={diffLookup.summaryDiff}
            enableContactLinks={enableContactLinks}
          />
        ) : null}

        <SectionsList
          sections={pageSections}
          t={t}
          settings={settings}
          layout={layout}
          isSidebarLayout={false}
          className={includeBasicInfo ? 'mt-7' : undefined}
          breakBeforeSectionSpacers={breakBeforeSectionSpacers}
          sectionDiffById={diffLookup.sectionDiffById}
          itemDiffById={diffLookup.itemDiffById}
        />
      </div>
    )
  }

  function renderPageBody(
    editableImages: boolean,
    pageSections = fullPreviewSections,
    includeBasicInfo = true,
    breakBeforeSectionSpacers?: Record<string, number>,
  ) {
    if (isSidebarLayout) {
      return (
        <>
          <TemplateImages
            images={layout.images}
            layout={layout}
            editable={editableImages}
            onMoveImage={onMoveTemplateImage}
          />
          <div
            className="relative z-10 grid min-h-[297mm] grid-cols-[64mm_minmax(0,1fr)]"
            data-resume-flow-content="true"
          >
            <SidebarBasicInfo
              t={t}
              basic={resume.basic}
              settings={settings}
              layout={layout}
              summaryDiff={diffLookup.summaryDiff}
              enableContactLinks={enableContactLinks}
            />
            <main
              className="min-w-0"
              style={{
                padding: `${settings.pagePaddingTop}mm ${settings.pagePaddingX}mm ${settings.pagePaddingBottom}mm`,
                backgroundColor: settings.pageBackground,
              }}
            >
              <SectionsList
                sections={pageSections}
                t={t}
                settings={settings}
                layout={layout}
                isSidebarLayout
                breakBeforeSectionSpacers={breakBeforeSectionSpacers}
                sectionDiffById={diffLookup.sectionDiffById}
                itemDiffById={diffLookup.itemDiffById}
              />
            </main>
          </div>
        </>
      )
    }

    return (
      <>
        <TemplateImages
          images={layout.images}
          layout={layout}
          editable={editableImages}
          onMoveImage={onMoveTemplateImage}
        />
        {renderStandardFlowContent(
          pageSections,
          includeBasicInfo,
          breakBeforeSectionSpacers,
        )}
      </>
    )
  }

  if (variant === 'thumbnail') {
    return (
      <article
        ref={ref}
        data-export-root="resume-page"
        className={pageClassName}
        style={pageStyle}
      >
        {renderPageBody(editableTemplateImages, fullPreviewSections, true)}
      </article>
    )
  }

  const pageIndexes = Array.from(
    { length: pagination.pageCount },
    (_, index) => index,
  )

  if (!isSidebarLayout) {
    return (
      <section
        ref={ref}
        className="resume-page-stack"
        data-resume-page-count={pagination.pageCount}
      >
        <div
          ref={measureRef}
          className="resume-page-content-flow resume-page-content-flow--measure"
          style={contentFlowStyle}
          aria-hidden="true"
        >
          {renderStandardFlowContent(
            fullPreviewSections,
            true,
            pagination.breakBeforeSectionSpacers,
          )}
        </div>

        {pageIndexes.map((pageIndex) => (
          <div className="resume-page-shell" key={pageIndex}>
            <p className="resume-page-label print:hidden">
              {`Page ${pageIndex + 1}`}
            </p>
            <article
              data-export-root="resume-page"
              className={cn(pageClassName, 'resume-page--content-paged')}
              style={pageStyle}
            >
              <TemplateImages
                images={layout.images}
                layout={layout}
                editable={editableTemplateImages}
                onMoveImage={onMoveTemplateImage}
              />
              <div
                className="resume-page-content-viewport"
                style={{
                  width: `${standardContentWidthMm}mm`,
                  height: `${standardContentHeightMm}mm`,
                }}
              >
                <div
                  className="resume-page-content-flow resume-page-content-fragment"
                  style={{
                    ...contentFlowStyle,
                    transform: `translateY(-${pageIndex * standardContentHeightMm}mm)`,
                  }}
                >
                  {renderStandardFlowContent(
                    fullPreviewSections,
                    true,
                    pagination.breakBeforeSectionSpacers,
                  )}
                </div>
              </div>
            </article>
          </div>
        ))}
      </section>
    )
  }

  return (
    <section
      ref={ref}
      className="resume-page-stack"
      data-resume-page-count={pagination.pageCount}
    >
      <div
        ref={measureRef}
        className={cn(
          'resume-page-flow resume-page-flow--measure',
          isSidebarLayout && 'resume-page-flow--sidebar',
        )}
        style={pageStyle}
        aria-hidden="true"
      >
        {renderPageBody(
          false,
          fullPreviewSections,
          true,
          pagination.breakBeforeSectionSpacers,
        )}
      </div>

      {pageIndexes.map((pageIndex) => (
        <div className="resume-page-shell" key={pageIndex}>
          <p className="resume-page-label print:hidden">
            {`Page ${pageIndex + 1}`}
          </p>
          <article
            data-export-root="resume-page"
            className={cn(pageClassName, 'resume-page--paged')}
            style={pageStyle}
          >
            <div
              className={cn(
                'resume-page-flow resume-page-fragment',
                isSidebarLayout && 'resume-page-flow--sidebar',
              )}
              style={{
                ...pageStyle,
                transform: `translateY(-${pageIndex * A4_HEIGHT_MM}mm)`,
              }}
            >
              {renderPageBody(
                editableTemplateImages,
                fullPreviewSections,
                true,
                pagination.breakBeforeSectionSpacers,
              )}
            </div>
          </article>
        </div>
      ))}
    </section>
  )
})
