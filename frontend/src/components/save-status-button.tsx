import { CircleCheck, LoaderCircle, Save } from 'lucide-react'

import type { Locale } from '@/i18n'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from '@/components/ui/hover-card'
import type { WorkspaceVersionSummary } from '@/types/api'

type SaveState = 'idle' | 'saving' | 'saved'

function formatSavedTime(locale: Locale, value: string | null) {
  if (!value) {
    return null
  }

  const formatter = new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })

  return formatter.format(new Date(value))
}

export function SaveStatusButton({
  locale,
  label,
  savingText,
  savedText,
  unsavedText,
  lastSavedLabel,
  state,
  hasUnsavedChanges,
  lastSavedAt,
  versions,
  activeVersionId,
  versionsLabel,
  currentVersionLabel,
  noVersionsText,
  onSave,
  onSelectVersion,
  showVersions = true,
}: {
  locale: Locale
  label: string
  savingText: string
  savedText: string
  unsavedText: string
  lastSavedLabel: string
  state: SaveState
  hasUnsavedChanges: boolean
  lastSavedAt: string | null
  versions: WorkspaceVersionSummary[]
  activeVersionId: string | null
  versionsLabel: string
  currentVersionLabel: string
  noVersionsText: string
  onSave: () => void
  onSelectVersion: (versionId: string) => void
  showVersions?: boolean
}) {
  const formattedTime = formatSavedTime(locale, lastSavedAt)
  const isSaving = state === 'saving'
  let tooltipText = savedText

  if (isSaving) {
    tooltipText = savingText
  } else if (hasUnsavedChanges) {
    tooltipText = unsavedText
  } else if (formattedTime) {
    tooltipText = `${savedText} · ${lastSavedLabel}: ${formattedTime}`
  }

  const saveButton = (
    <Button
      type="button"
      variant="outline"
      size="icon"
      aria-label={label}
      title={showVersions ? undefined : tooltipText}
      disabled={isSaving}
      onClick={onSave}
    >
      {isSaving ? (
        <LoaderCircle className="animate-spin" />
      ) : hasUnsavedChanges ? (
        <Save />
      ) : (
        <CircleCheck />
      )}
    </Button>
  )

  if (!showVersions) {
    return saveButton
  }

  return (
    <HoverCard openDelay={250} closeDelay={150}>
      <HoverCardTrigger asChild>{saveButton}</HoverCardTrigger>
      <HoverCardContent align="end" className="w-64 p-2 text-xs">
        <p className="px-2 py-1 text-muted-foreground">{tooltipText}</p>
        <div className="mt-1 border-t border-border/70 pt-1">
          <p className="px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            {versionsLabel}
          </p>
          {versions.length > 0 ? (
            <div className="max-h-56 overflow-y-auto overscroll-contain">
              {versions.map((version) => {
                const isActive = version.versionId === activeVersionId
                const savedTime = formatSavedTime(locale, version.savedAt)

                return (
                  <Button
                    key={version.versionId}
                    type="button"
                    variant="ghost"
                    className="h-auto w-full justify-between gap-3 px-2 py-2 text-left font-normal"
                    onClick={() => onSelectVersion(version.versionId)}
                  >
                    <span className="min-w-0 truncate">
                      {savedTime ?? version.versionId}
                    </span>
                    {isActive ? (
                      <Badge className="shrink-0 text-[10px]">
                        {currentVersionLabel}
                      </Badge>
                    ) : null}
                  </Button>
                )
              })}
            </div>
          ) : (
            <p className="px-2 py-2 text-muted-foreground">{noVersionsText}</p>
          )}
        </div>
      </HoverCardContent>
    </HoverCard>
  )
}
