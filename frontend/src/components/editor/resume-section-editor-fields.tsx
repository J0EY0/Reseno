import { Suspense, lazy, useState } from 'react'

import { FieldLegend, FieldSet } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import type { AppMessages } from '@/i18n'
import { isRichTextEmpty, serializeHighlightsToHtml } from '@/lib/rich-text'
import { parseCommaSeparatedItems } from '@/lib/resume-sections'

const RichHighlightsEditor = lazy(() =>
  import('./rich-highlights-editor').then((module) => ({
    default: module.RichHighlightsEditor,
  })),
)

export const compactResumeFieldClassName =
  'border-border/60 bg-muted/35 shadow-none focus-visible:border-ring/50 focus-visible:ring-1 focus-visible:ring-ring/20'

function RichHighlightsEditorSkeleton({ value }: { value: string[] }) {
  const editorValue = serializeHighlightsToHtml(value)

  return (
    <div className="overflow-hidden rounded-lg border border-border/70 bg-muted/30">
      <div className="flex flex-wrap items-center gap-1 border-b border-border/60 bg-muted/25 px-2 py-1">
        {Array.from({ length: 7 }, (_, index) => (
          <Skeleton key={index} className="size-8 rounded-md" />
        ))}
      </div>
      <div className="min-h-[140px] bg-background/65 px-3 py-2.5">
        <Skeleton>
          <div
            aria-hidden="true"
            className="tiptap rich-text-editor rich-text-editor-scroll invisible max-h-[160px] min-h-[120px] cursor-text overflow-y-auto overscroll-contain text-sm leading-[1.12] text-foreground outline-none"
            dangerouslySetInnerHTML={{ __html: editorValue || '<p></p>' }}
          />
        </Skeleton>
      </div>
    </div>
  )
}

export function HighlightsField({
  t,
  value,
  onChange,
}: {
  t: AppMessages
  value: string[]
  onChange: (value: string[]) => void
}) {
  return (
    <FieldSet className="min-w-0 gap-2 md:col-span-2">
      <FieldLegend
        variant="label"
        className="mb-0 break-words text-xs leading-tight text-muted-foreground"
      >
        {t.fieldLabels.highlights}
      </FieldLegend>
      <Suspense fallback={<RichHighlightsEditorSkeleton value={value} />}>
        <RichHighlightsEditor
          t={t}
          value={value}
          onChange={(nextValue) =>
            onChange(isRichTextEmpty(nextValue) ? [] : [nextValue])
          }
        />
      </Suspense>
    </FieldSet>
  )
}

export function SimpleContentField({
  t,
  value,
  onChange,
}: {
  t: AppMessages
  value: string
  onChange: (value: string) => void
}) {
  return (
    <FieldSet className="min-w-0 gap-2">
      <FieldLegend
        variant="label"
        className="mb-0 break-words text-xs leading-tight text-muted-foreground"
      >
        {t.fieldLabels.content}
      </FieldLegend>
      <Suspense
        fallback={
          <RichHighlightsEditorSkeleton
            value={isRichTextEmpty(value) ? [] : [value]}
          />
        }
      >
        <RichHighlightsEditor
          t={t}
          value={isRichTextEmpty(value) ? [] : [value]}
          onChange={onChange}
        />
      </Suspense>
    </FieldSet>
  )
}

export function CommaSeparatedInput({
  id,
  value,
  placeholder,
  onChange,
}: {
  id?: string
  value: string[]
  placeholder: string
  onChange: (value: string[]) => void
}) {
  const serializedValue = value.join(', ')
  const [inputState, setInputState] = useState(() => ({
    draft: serializedValue,
    publishedValue: serializedValue,
  }))
  const displayedValue =
    inputState.publishedValue === serializedValue
      ? inputState.draft
      : serializedValue

  function publishValue(nextDraft: string) {
    const nextValue = parseCommaSeparatedItems(nextDraft)
    setInputState({
      draft: nextDraft,
      publishedValue: nextValue.join(', '),
    })
    onChange(nextValue)
  }

  return (
    <Input
      id={id}
      value={displayedValue}
      className={compactResumeFieldClassName}
      placeholder={placeholder}
      onFocus={() => {
        // Adopt an Agent/version update as the next local draft while keeping
        // our own canonical publishes from disturbing the caret while typing.
        if (serializedValue !== inputState.publishedValue) {
          setInputState({
            draft: serializedValue,
            publishedValue: serializedValue,
          })
        }
      }}
      onChange={(event) => {
        publishValue(event.target.value)
      }}
      onBlur={(event) => {
        const normalizedValue = parseCommaSeparatedItems(event.currentTarget.value)
        const normalizedDraft = normalizedValue.join(', ')
        setInputState({
          draft: normalizedDraft,
          publishedValue: normalizedDraft,
        })
        onChange(normalizedValue)
      }}
    />
  )
}
