import { ChevronDown, type LucideIcon } from 'lucide-react'
import { useEffect, useRef, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { cn } from '@/lib/utils'

const EDITOR_CARD_SCROLL_TOP_OFFSET = 8
const EDITOR_CARD_SCROLL_SYNC_FRAMES = 34
const EDITOR_CARD_SCROLL_EASE = 0.34
const EDITOR_CARD_SCROLL_SETTLE_THRESHOLD = 6
const EDITOR_CARD_SCROLL_DYNAMIC_BUFFER_MAX = 32
const EDITOR_CARD_SCROLL_LAYOUT_SHIFT_THRESHOLD = 1.5
const EDITOR_CARD_SCROLL_BUFFER_DECAY = 2.5
type CardScrollTarget = 'editor' | 'page'

function getCardScrollCorrection(
  cardTop: number,
  visibleTop: number,
  dynamicBuffer: number,
) {
  return cardTop - visibleTop - dynamicBuffer
}

export function EditorCardShell({
  icon: Icon,
  title,
  summary,
  toggleLabel,
  collapsed,
  onToggle,
  headerAction,
  children,
}: {
  icon: LucideIcon
  title: string
  summary: string
  toggleLabel: string
  collapsed: boolean
  onToggle: () => void
  headerAction?: ReactNode
  children: ReactNode
}) {
  const cardRef = useRef<HTMLDivElement | null>(null)
  const previousCollapsedRef = useRef(collapsed)

  useEffect(() => {
    const wasCollapsed = previousCollapsedRef.current
    previousCollapsedRef.current = collapsed

    if (!wasCollapsed || collapsed) {
      return
    }

    const cardElement = cardRef.current

    if (!cardElement) {
      return
    }

    const element = cardElement
    const prefersReducedMotion = window.matchMedia(
      '(prefers-reduced-motion: reduce)',
    ).matches
    const pageScrollBehavior: ScrollBehavior = prefersReducedMotion ? 'auto' : 'smooth'
    let dynamicTopBuffer = 0
    let previousMeasurement: {
      cardTop: number
      scrollPosition: number
      target: CardScrollTarget
    } | null = null

    function getDynamicTopBuffer(
      cardTop: number,
      scrollPosition: number,
      target: CardScrollTarget,
      settle: boolean,
    ) {
      if (settle || previousMeasurement?.target !== target) {
        dynamicTopBuffer = 0
        previousMeasurement = { cardTop, scrollPosition, target }
        return dynamicTopBuffer
      }

      if (previousMeasurement) {
        const layoutShift =
          cardTop -
          previousMeasurement.cardTop +
          scrollPosition -
          previousMeasurement.scrollPosition

        if (layoutShift < -EDITOR_CARD_SCROLL_LAYOUT_SHIFT_THRESHOLD) {
          dynamicTopBuffer = Math.min(
            EDITOR_CARD_SCROLL_DYNAMIC_BUFFER_MAX,
            dynamicTopBuffer + Math.abs(layoutShift) * 0.65,
          )
        } else {
          dynamicTopBuffer = Math.max(
            0,
            dynamicTopBuffer - EDITOR_CARD_SCROLL_BUFFER_DECAY,
          )
        }
      }

      previousMeasurement = { cardTop, scrollPosition, target }
      return dynamicTopBuffer
    }

    function scrollCardToTop(settle = false) {
      const scrollContainer = element.closest<HTMLElement>('.resume-editor-panel')
      const headerElement = document.querySelector<HTMLElement>(
        '.app-shell--document > header',
      )
      const headerBottom = headerElement?.getBoundingClientRect().bottom ?? 0

      if (
        scrollContainer &&
        scrollContainer.scrollHeight > scrollContainer.clientHeight + 1
      ) {
        const containerTop = scrollContainer.getBoundingClientRect().top
        const visibleTop =
          Math.max(containerTop, headerBottom) + EDITOR_CARD_SCROLL_TOP_OFFSET
        const cardTop = element.getBoundingClientRect().top
        const dynamicBuffer = getDynamicTopBuffer(
          cardTop,
          scrollContainer.scrollTop + window.scrollY,
          'editor',
          settle,
        )
        const correction = getCardScrollCorrection(
          cardTop,
          visibleTop,
          dynamicBuffer,
        )

        if (Math.abs(correction) > 1) {
          const delta =
            prefersReducedMotion || settle
              ? correction
              : correction * EDITOR_CARD_SCROLL_EASE
          const previousScrollTop = scrollContainer.scrollTop

          scrollContainer.scrollTop += delta
          const remainingDelta =
            delta - (scrollContainer.scrollTop - previousScrollTop)

          if (Math.abs(remainingDelta) > 1) {
            window.scrollBy({
              top: remainingDelta,
              behavior: pageScrollBehavior,
            })
          }
        }
        return
      }

      const visibleTop = headerBottom + EDITOR_CARD_SCROLL_TOP_OFFSET
      const cardTop = element.getBoundingClientRect().top
      const dynamicBuffer = getDynamicTopBuffer(
        cardTop,
        window.scrollY,
        'page',
        settle,
      )
      const correction = getCardScrollCorrection(
        cardTop,
        visibleTop,
        dynamicBuffer,
      )

      if (Math.abs(correction) <= 1) {
        return
      }

      const delta =
        prefersReducedMotion || settle
          ? correction
          : correction * EDITOR_CARD_SCROLL_EASE

      window.scrollBy({
        top: delta,
        behavior: pageScrollBehavior,
      })
    }

    let remainingFrames = EDITOR_CARD_SCROLL_SYNC_FRAMES
    let animationFrame = 0

    const syncDuringCollapseAnimation = () => {
      scrollCardToTop()
      remainingFrames -= 1

      if (remainingFrames > 0) {
        animationFrame = window.requestAnimationFrame(syncDuringCollapseAnimation)
      }
    }

    animationFrame = window.requestAnimationFrame(syncDuringCollapseAnimation)
    const settleTimer = window.setTimeout(() => {
      const scrollContainer = element.closest<HTMLElement>('.resume-editor-panel')
      const headerElement = document.querySelector<HTMLElement>(
        '.app-shell--document > header',
      )
      const headerBottom = headerElement?.getBoundingClientRect().bottom ?? 0
      const visibleTop = scrollContainer
        ? Math.max(
            scrollContainer.getBoundingClientRect().top,
            headerBottom,
          ) + EDITOR_CARD_SCROLL_TOP_OFFSET
        : headerBottom + EDITOR_CARD_SCROLL_TOP_OFFSET
      const cardTop = element.getBoundingClientRect().top
      const correction = getCardScrollCorrection(
        cardTop,
        visibleTop,
        0,
      )

      if (Math.abs(correction) > EDITOR_CARD_SCROLL_SETTLE_THRESHOLD) {
        scrollCardToTop(true)
      }
    }, 360)

    return () => {
      window.cancelAnimationFrame(animationFrame)
      window.clearTimeout(settleTimer)
    }
  }, [collapsed])

  return (
    <Card
      ref={cardRef}
      data-collapsed={collapsed ? 'true' : 'false'}
      className={cn(
        'gap-0 overflow-hidden rounded-xl border-border/75 py-0 shadow-xs transition-[border-color,box-shadow] duration-200 ease-[cubic-bezier(0.16,1,0.3,1)]',
        !collapsed && 'border-primary/20',
      )}
    >
      <Collapsible open={!collapsed} onOpenChange={onToggle}>
        <div className="flex min-h-[60px] items-center justify-between gap-3 px-4 py-3">
          <div className="grid min-w-0 flex-1 grid-cols-[2.25rem_minmax(0,1fr)] items-center gap-2.5">
            <div className="flex size-9 items-center justify-center rounded-xl bg-primary/8 text-primary">
              <Icon className="size-4" />
            </div>
            <div className="min-w-0">
              <h3 className="truncate text-sm font-semibold leading-5 tracking-tight" title={title}>
                {title}
              </h3>
              <p className="mt-0.5 truncate text-xs leading-4 text-muted-foreground" title={summary}>
                {summary}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {headerAction}
            <CollapsibleTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="icon"
                aria-label={toggleLabel}
              >
                <ChevronDown
                  className={cn('size-4 transition-transform', collapsed && '-rotate-90')}
                />
                <span className="sr-only">{toggleLabel}</span>
              </Button>
            </CollapsibleTrigger>
          </div>
        </div>
        <CollapsibleContent className="collapsible-content">
          <CardContent className="collapsible-content-inner grid gap-4 border-t border-border/70 p-4">
            {children}
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}
