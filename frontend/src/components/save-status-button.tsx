import { CheckCheck, History, LoaderCircle, Save } from 'lucide-react'
import { useState } from 'react'

import type { Locale } from '@/i18n'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ButtonGroup } from '@/components/ui/button-group'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
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
  const [isHistoryOpen, setIsHistoryOpen] = useState(false)
  const formattedTime = formatSavedTime(locale, lastSavedAt)
  const tooltipText =
    state === 'saving'
      ? savingText
      : state === 'saved' && formattedTime
        ? `${savedText} · ${lastSavedLabel}: ${formattedTime}`
        : formattedTime
          ? `${lastSavedLabel}: ${formattedTime}`
          : unsavedText

  const saveButton = (
    <Button
      type="button"
      variant="outline"
      size="icon"
      aria-label={label}
      title={tooltipText}
      disabled={state === 'saving'}
      onClick={onSave}
    >
      {state === 'saving' ? (
        <LoaderCircle className="size-4 animate-spin" />
      ) : state === 'saved' ? (
        <CheckCheck className="size-4" />
      ) : (
        <Save className="size-4" />
      )}
    </Button>
  )

  if (!showVersions) {
    return saveButton
  }

  return (
    <ButtonGroup aria-label={`${label} / ${versionsLabel}`}>
      {saveButton}
      <Popover open={isHistoryOpen} onOpenChange={setIsHistoryOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label={versionsLabel}
            title={versionsLabel}
          >
            <History />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-64 p-2 text-xs">
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
                      onClick={() => {
                        setIsHistoryOpen(false)
                        onSelectVersion(version.versionId)
                      }}
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
        </PopoverContent>
      </Popover>
    </ButtonGroup>
  )
}
