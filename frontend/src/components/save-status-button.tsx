import { CheckCheck, LoaderCircle, Save } from 'lucide-react'

import type { Locale } from '@/i18n'
import { Button } from '@/components/ui/button'
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
  const formattedTime = formatSavedTime(locale, lastSavedAt)
  const tooltipText =
    state === 'saving'
      ? savingText
      : state === 'saved' && formattedTime
        ? `${savedText} · ${lastSavedLabel}: ${formattedTime}`
        : formattedTime
          ? `${lastSavedLabel}: ${formattedTime}`
          : unsavedText

  return (
    <div className="group relative">
      <Button
        type="button"
        variant="outline"
        size="icon"
        aria-label={label}
        title={tooltipText}
        className="relative"
        disabled={state === 'saving'}
        onClick={onSave}
      >
        {state === 'saving' ? (
          <LoaderCircle className="size-4 animate-spin" />
        ) : state === 'saved' ? (
          <CheckCheck className="size-4" />
        ) : (
          <Save className="size-4 transition-transform group-hover:scale-110" />
        )}
      </Button>
      {showVersions ? (
        <div className="absolute right-0 top-full z-30 hidden w-64 pt-2 group-hover:block">
          <div className="rounded-xl border border-border bg-popover p-2 text-xs text-popover-foreground shadow-lg">
            <p className="px-2 py-1 text-muted-foreground">{tooltipText}</p>
            <div className="mt-1 border-t border-border/70 pt-1">
              <p className="px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                {versionsLabel}
              </p>
              {versions.length > 0 ? (
                <div className="max-h-56 overflow-y-auto">
                  {versions.map((version) => {
                    const isActive = version.versionId === activeVersionId
                    const savedTime = formatSavedTime(locale, version.savedAt)

                    return (
                      <button
                        key={version.versionId}
                        type="button"
                        className="flex w-full items-center justify-between gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-accent hover:text-accent-foreground"
                        onClick={() => onSelectVersion(version.versionId)}
                      >
                        <span className="min-w-0 truncate">
                          {savedTime ?? version.versionId}
                        </span>
                        {isActive ? (
                          <span className="shrink-0 rounded-full bg-primary px-2 py-0.5 text-[10px] text-primary-foreground">
                            {currentVersionLabel}
                          </span>
                        ) : null}
                      </button>
                    )
                  })}
                </div>
              ) : (
                <p className="px-2 py-2 text-muted-foreground">
                  {noVersionsText}
                </p>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
