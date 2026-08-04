import { ChevronDown, Trash2 } from 'lucide-react'
import { Suspense, lazy, useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { FieldLegend, FieldSet } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import type { AppMessages } from '@/i18n'
import { isRichTextEmpty } from '@/lib/rich-text'
import type { ResumeSectionMutation } from '@/lib/resume-sections'
import { cn } from '@/lib/utils'
import type {
  AchievementItem,
  EducationItem,
  ExperienceItem,
  ProjectItem,
  ResumeSection,
  ResumeSectionOf,
  SimpleListItem,
} from '@/types/resume'

import { FormField } from './form-field'

const RichHighlightsEditor = lazy(() =>
  import('./rich-highlights-editor').then((module) => ({
    default: module.RichHighlightsEditor,
  })),
)

const compactFieldClassName =
  'border-border/60 bg-muted/35 shadow-none focus-visible:border-ring/50 focus-visible:ring-1 focus-visible:ring-ring/20'

type ItemUpdateMutation = Extract<
  ResumeSectionMutation,
  { type: 'item.update' }
>

type SectionItemsEditorProps = {
  t: AppMessages
  section: ResumeSection
  onMutation: (mutation: ResumeSectionMutation) => void
}

type TypedSectionEditorProps<K extends ResumeSection['kind']> = {
  t: AppMessages
  section: ResumeSectionOf<K>
  onUpdateItem: (mutation: ItemUpdateMutation) => void
  onRemoveItem: (itemId: string) => void
}

function RichHighlightsEditorSkeleton() {
  return (
    <div className="overflow-hidden rounded-lg border border-border/70 bg-muted/30">
      <div className="flex items-center gap-1 border-b border-border/60 bg-muted/25 px-2 py-1">
        {Array.from({ length: 8 }, (_, index) => (
          <Skeleton key={index} className="size-8 rounded-md" />
        ))}
      </div>
      <Skeleton className="h-[120px] rounded-none" />
    </div>
  )
}

function ItemEditorShell({
  index,
  itemLabel,
  removeLabel,
  toggleLabel,
  onRemove,
  children,
}: {
  index: number
  itemLabel: string
  removeLabel: string
  toggleLabel: string
  onRemove: () => void
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)

  return (
    <>
      {index > 0 ? <Separator /> : null}
      <section>
        <Collapsible
          open={open}
          onOpenChange={setOpen}
          className="-mx-2 rounded-md bg-muted/35"
        >
          <div className="flex min-h-10 items-center justify-between gap-3 px-2">
            <h4 className="text-sm font-medium text-foreground/80">
              {itemLabel} {index + 1}
            </h4>
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`${removeLabel} ${index + 1}`}
                onClick={onRemove}
              >
                <Trash2 aria-hidden="true" />
              </Button>
              <CollapsibleTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={`${toggleLabel} ${index + 1}`}
                >
                  <ChevronDown
                    aria-hidden="true"
                    className={cn(
                      'transition-transform',
                      !open && '-rotate-90',
                    )}
                  />
                </Button>
              </CollapsibleTrigger>
            </div>
          </div>
          <CollapsibleContent className="collapsible-content">
            <div className="collapsible-content-inner grid gap-3 px-2 pb-2 pt-3">
              {children}
            </div>
          </CollapsibleContent>
        </Collapsible>
      </section>
    </>
  )
}

function HighlightsField({
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
      <Suspense fallback={<RichHighlightsEditorSkeleton />}>
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

function SimpleContentField({
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
      <Suspense fallback={<RichHighlightsEditorSkeleton />}>
        <RichHighlightsEditor
          t={t}
          value={isRichTextEmpty(value) ? [] : [value]}
          onChange={onChange}
        />
      </Suspense>
    </FieldSet>
  )
}

function CommaSeparatedInput({
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

  function commitValue(input: HTMLInputElement) {
    const nextValue = input.value
      .split(/[,，]/)
      .map((item) => item.trim())
      .filter(Boolean)

    input.value = nextValue.join(', ')
    onChange(nextValue)
  }

  return (
    <Input
      id={id}
      key={serializedValue}
      defaultValue={serializedValue}
      className={compactFieldClassName}
      placeholder={placeholder}
      onBlur={(event) => commitValue(event.currentTarget)}
    />
  )
}

function EducationSectionEditor({
  t,
  section,
  onUpdateItem,
  onRemoveItem,
}: TypedSectionEditorProps<'education'>) {
  function updateItem(
    item: EducationItem,
    patch: Partial<Omit<EducationItem, 'id'>>,
  ) {
    onUpdateItem({
      type: 'item.update',
      sectionId: section.id,
      sectionKind: 'education',
      itemId: item.id,
      patch,
    })
  }

  return section.items.map((item, index) => (
    <ItemEditorShell
      key={item.id}
      index={index}
      itemLabel={t.itemCountSingular}
      removeLabel={t.removeItem}
      toggleLabel={t.toggleItem}
      onRemove={() => onRemoveItem(item.id)}
    >
      <div className="grid min-w-0 gap-3 md:grid-cols-2">
        <FormField label={t.fieldLabels.school}>
          <Input
            value={item.school}
            className={compactFieldClassName}
            placeholder={t.placeholders.school}
            onChange={(event) => updateItem(item, { school: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.degree}>
          <Input
            value={item.degree}
            className={compactFieldClassName}
            placeholder={t.placeholders.degree}
            onChange={(event) => updateItem(item, { degree: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.major}>
          <Input
            value={item.major}
            className={compactFieldClassName}
            placeholder={t.placeholders.major}
            onChange={(event) => updateItem(item, { major: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.gpa}>
          <Input
            value={item.gpa}
            className={compactFieldClassName}
            placeholder={t.placeholders.gpa}
            onChange={(event) => updateItem(item, { gpa: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.location}>
          <Input
            value={item.location}
            className={compactFieldClassName}
            placeholder={t.placeholders.location}
            onChange={(event) => updateItem(item, { location: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.period}>
          <Input
            value={item.period}
            className={compactFieldClassName}
            placeholder={t.placeholders.period}
            onChange={(event) => updateItem(item, { period: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.description} className="md:col-span-2">
          <Textarea
            rows={2}
            value={item.description}
            className={`${compactFieldClassName} min-h-16 resize-y`}
            placeholder={t.placeholders.description}
            onChange={(event) => updateItem(item, { description: event.target.value })}
          />
        </FormField>
        <HighlightsField
          t={t}
          value={item.highlights}
          onChange={(highlights) => updateItem(item, { highlights })}
        />
      </div>
    </ItemEditorShell>
  ))
}

function ExperienceSectionEditor({
  t,
  section,
  onUpdateItem,
  onRemoveItem,
}: TypedSectionEditorProps<'experience'>) {
  function updateItem(
    item: ExperienceItem,
    patch: Partial<Omit<ExperienceItem, 'id'>>,
  ) {
    onUpdateItem({
      type: 'item.update',
      sectionId: section.id,
      sectionKind: 'experience',
      itemId: item.id,
      patch,
    })
  }

  return section.items.map((item, index) => (
    <ItemEditorShell
      key={item.id}
      index={index}
      itemLabel={t.itemCountSingular}
      removeLabel={t.removeItem}
      toggleLabel={t.toggleItem}
      onRemove={() => onRemoveItem(item.id)}
    >
      <div className="grid min-w-0 gap-3 md:grid-cols-2">
        <FormField label={t.fieldLabels.company}>
          <Input
            value={item.company}
            className={compactFieldClassName}
            placeholder={t.placeholders.company}
            onChange={(event) => updateItem(item, { company: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.position}>
          <Input
            value={item.position}
            className={compactFieldClassName}
            placeholder={t.placeholders.position}
            onChange={(event) => updateItem(item, { position: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.location}>
          <Input
            value={item.location}
            className={compactFieldClassName}
            placeholder={t.placeholders.location}
            onChange={(event) => updateItem(item, { location: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.period}>
          <Input
            value={item.period}
            className={compactFieldClassName}
            placeholder={t.placeholders.period}
            onChange={(event) => updateItem(item, { period: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.description} className="md:col-span-2">
          <Textarea
            rows={2}
            value={item.description}
            className={`${compactFieldClassName} min-h-16 resize-y`}
            placeholder={t.placeholders.description}
            onChange={(event) => updateItem(item, { description: event.target.value })}
          />
        </FormField>
        <HighlightsField
          t={t}
          value={item.highlights}
          onChange={(highlights) => updateItem(item, { highlights })}
        />
      </div>
    </ItemEditorShell>
  ))
}

function ProjectSectionEditor({
  t,
  section,
  onUpdateItem,
  onRemoveItem,
}: TypedSectionEditorProps<'project'>) {
  function updateItem(
    item: ProjectItem,
    patch: Partial<Omit<ProjectItem, 'id'>>,
  ) {
    onUpdateItem({
      type: 'item.update',
      sectionId: section.id,
      sectionKind: 'project',
      itemId: item.id,
      patch,
    })
  }

  return section.items.map((item, index) => (
    <ItemEditorShell
      key={item.id}
      index={index}
      itemLabel={t.itemCountSingular}
      removeLabel={t.removeItem}
      toggleLabel={t.toggleItem}
      onRemove={() => onRemoveItem(item.id)}
    >
      <div className="grid min-w-0 gap-3 md:grid-cols-2">
        <FormField label={t.fieldLabels.projectName}>
          <Input
            value={item.name}
            className={compactFieldClassName}
            placeholder={t.placeholders.projectName}
            onChange={(event) => updateItem(item, { name: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.role}>
          <Input
            value={item.role}
            className={compactFieldClassName}
            placeholder={t.placeholders.role}
            onChange={(event) => updateItem(item, { role: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.techStack}>
          <CommaSeparatedInput
            value={item.techStack}
            placeholder={t.placeholders.techStack}
            onChange={(techStack) => updateItem(item, { techStack })}
          />
        </FormField>
        <FormField label={t.fieldLabels.period}>
          <Input
            value={item.period}
            className={compactFieldClassName}
            placeholder={t.placeholders.period}
            onChange={(event) => updateItem(item, { period: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.url} className="md:col-span-2">
          <Input
            type="url"
            inputMode="url"
            value={item.url}
            className={compactFieldClassName}
            placeholder={t.placeholders.url}
            onChange={(event) => updateItem(item, { url: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.description} className="md:col-span-2">
          <Textarea
            rows={2}
            value={item.description}
            className={`${compactFieldClassName} min-h-16 resize-y`}
            placeholder={t.placeholders.description}
            onChange={(event) => updateItem(item, { description: event.target.value })}
          />
        </FormField>
        <HighlightsField
          t={t}
          value={item.highlights}
          onChange={(highlights) => updateItem(item, { highlights })}
        />
      </div>
    </ItemEditorShell>
  ))
}

function AchievementSectionEditor({
  t,
  section,
  onUpdateItem,
  onRemoveItem,
}: TypedSectionEditorProps<'achievement'>) {
  function updateItem(
    item: AchievementItem,
    patch: Partial<Omit<AchievementItem, 'id'>>,
  ) {
    onUpdateItem({
      type: 'item.update',
      sectionId: section.id,
      sectionKind: 'achievement',
      itemId: item.id,
      patch,
    })
  }

  return section.items.map((item, index) => (
    <ItemEditorShell
      key={item.id}
      index={index}
      itemLabel={t.itemCountSingular}
      removeLabel={t.removeItem}
      toggleLabel={t.toggleItem}
      onRemove={() => onRemoveItem(item.id)}
    >
      <div className="grid min-w-0 gap-3 md:grid-cols-2">
        <FormField label={t.fieldLabels.achievementName}>
          <Input
            value={item.name}
            className={compactFieldClassName}
            placeholder={t.placeholders.achievementName}
            onChange={(event) => updateItem(item, { name: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.issuer}>
          <Input
            value={item.issuer}
            className={compactFieldClassName}
            placeholder={t.placeholders.issuer}
            onChange={(event) => updateItem(item, { issuer: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.date}>
          <Input
            value={item.date}
            className={compactFieldClassName}
            placeholder={t.placeholders.date}
            onChange={(event) => updateItem(item, { date: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.url}>
          <Input
            type="url"
            inputMode="url"
            value={item.url}
            className={compactFieldClassName}
            placeholder={t.placeholders.url}
            onChange={(event) => updateItem(item, { url: event.target.value })}
          />
        </FormField>
        <FormField label={t.fieldLabels.description} className="md:col-span-2">
          <Textarea
            rows={2}
            value={item.description}
            className={`${compactFieldClassName} min-h-16 resize-y`}
            placeholder={t.placeholders.description}
            onChange={(event) => updateItem(item, { description: event.target.value })}
          />
        </FormField>
      </div>
    </ItemEditorShell>
  ))
}

function SimpleListSectionEditor({
  t,
  section,
  onUpdateItem,
}: Omit<TypedSectionEditorProps<'simple_list'>, 'onRemoveItem'>) {
  const item = section.items[0]

  function updateItem(
    item: SimpleListItem,
    patch: Partial<Omit<SimpleListItem, 'id'>>,
  ) {
    onUpdateItem({
      type: 'item.update',
      sectionId: section.id,
      sectionKind: 'simple_list',
      itemId: item.id,
      patch,
    })
  }

  return (
    <SimpleContentField
      t={t}
      value={item.content}
      onChange={(content) => updateItem(item, { content })}
    />
  )
}

export function ResumeSectionItemsEditor({
  t,
  section,
  onMutation,
}: SectionItemsEditorProps) {
  const onRemoveItem = (itemId: string) => {
    onMutation({ type: 'item.remove', sectionId: section.id, itemId })
  }
  const onUpdateItem = (mutation: ItemUpdateMutation) => onMutation(mutation)

  switch (section.kind) {
    case 'education':
      return (
        <EducationSectionEditor
          t={t}
          section={section}
          onUpdateItem={onUpdateItem}
          onRemoveItem={onRemoveItem}
        />
      )
    case 'experience':
      return (
        <ExperienceSectionEditor
          t={t}
          section={section}
          onUpdateItem={onUpdateItem}
          onRemoveItem={onRemoveItem}
        />
      )
    case 'project':
      return (
        <ProjectSectionEditor
          t={t}
          section={section}
          onUpdateItem={onUpdateItem}
          onRemoveItem={onRemoveItem}
        />
      )
    case 'achievement':
      return (
        <AchievementSectionEditor
          t={t}
          section={section}
          onUpdateItem={onUpdateItem}
          onRemoveItem={onRemoveItem}
        />
      )
    case 'simple_list':
      return (
        <SimpleListSectionEditor
          t={t}
          section={section}
          onUpdateItem={onUpdateItem}
        />
      )
  }
}
