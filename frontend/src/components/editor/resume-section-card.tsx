import {
  ArrowDown,
  ArrowUp,
  Award,
  BadgeCheck,
  Briefcase,
  FolderKanban,
  GraduationCap,
  Languages,
  List,
  Plus,
  Sparkles,
  Trash2,
  Wrench,
  type LucideIcon,
} from 'lucide-react'
import { Suspense, lazy } from 'react'

import type { AppMessages } from '@/i18n'
import { getSectionSummary, getSectionTitle } from '@/lib/resume'
import type {
  ResumeSection,
  ResumeSectionItem,
  SectionKind,
} from '@/types/resume'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'

import { EditorCardShell } from './editor-card-shell'
import { FormField } from './form-field'

const RichHighlightsEditor = lazy(() =>
  import('./rich-highlights-editor').then((module) => ({
    default: module.RichHighlightsEditor,
  })),
)

const sectionIcons: Record<SectionKind, LucideIcon> = {
  education: GraduationCap,
  work: Briefcase,
  internship: Briefcase,
  project: FolderKanban,
  skills: Wrench,
  awards: Award,
  certificates: BadgeCheck,
  languages: Languages,
  other: List,
  custom: Sparkles,
}

const compactFieldClassName =
  'border-border/60 bg-muted/35 shadow-none focus-visible:border-ring/50 focus-visible:ring-1 focus-visible:ring-ring/20'

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

export function ResumeSectionCard({
  t,
  section,
  collapsed,
  onToggle,
  onUpdateSection,
  onAddItem,
  onRemoveSection,
  onMoveSectionDown,
  onMoveSectionUp,
  onUpdateItem,
  onUpdateHighlights,
  onRemoveItem,
  canMoveUp,
  canMoveDown,
}: {
  t: AppMessages
  section: ResumeSection
  collapsed: boolean
  onToggle: () => void
  onUpdateSection: (
    sectionId: string,
    patch: Partial<Omit<ResumeSection, 'id' | 'items'>>,
  ) => void
  onAddItem: (sectionId: string) => void
  onRemoveSection: (sectionId: string) => void
  onMoveSectionUp: (sectionId: string) => void
  onMoveSectionDown: (sectionId: string) => void
  onUpdateItem: (
    sectionId: string,
    itemId: string,
    field: keyof Omit<ResumeSectionItem, 'id' | 'highlights'>,
    value: string,
  ) => void
  onUpdateHighlights: (sectionId: string, itemId: string, value: string) => void
  onRemoveItem: (sectionId: string, itemId: string) => void
  canMoveUp: boolean
  canMoveDown: boolean
}) {
  const Icon = sectionIcons[section.kind]
  const sectionTitle = getSectionTitle(section, t)

  return (
    <EditorCardShell
      icon={Icon}
      title={sectionTitle}
      summary={getSectionSummary(section, t)}
      toggleLabel={`${sectionTitle}: ${t.toggleSection}`}
      collapsed={collapsed}
      onToggle={onToggle}
      headerAction={
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            disabled={!canMoveUp}
            onClick={() => onMoveSectionUp(section.id)}
          >
            <ArrowUp className="size-4" />
            <span className="sr-only">{`${sectionTitle}: ${t.moveSectionUp}`}</span>
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            disabled={!canMoveDown}
            onClick={() => onMoveSectionDown(section.id)}
          >
            <ArrowDown className="size-4" />
            <span className="sr-only">{`${sectionTitle}: ${t.moveSectionDown}`}</span>
          </Button>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={(event) => event.stopPropagation()}
              >
                <Trash2 className="size-4" />
                <span className="sr-only">{`${sectionTitle}: ${t.deleteSection}`}</span>
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent size="sm">
              <AlertDialogHeader>
                <AlertDialogTitle>
                  {t.confirmDeleteSectionTitle}
                </AlertDialogTitle>
                <AlertDialogDescription>
                  {t.confirmDeleteSectionDescription}
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>{t.cancel}</AlertDialogCancel>
                <AlertDialogAction
                  variant="destructive"
                  onClick={() => onRemoveSection(section.id)}
                >
                  {t.deleteSection}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      }
    >
      <div className="grid min-w-0 gap-3">
        <FormField label={t.renameSection}>
          <Input
            value={section.customTitle}
            className={compactFieldClassName}
            placeholder={t.placeholders.sectionName}
            onChange={(event) =>
              onUpdateSection(section.id, { customTitle: event.target.value })
            }
          />
        </FormField>
        <Button
          type="button"
          variant="outline"
          className="self-start"
          onClick={() => onAddItem(section.id)}
        >
          <Plus className="size-4" />
          {t.addItem}
        </Button>
      </div>

      <div className="grid gap-3">
        {section.items.map((item, index) => (
          <div key={item.id} className="grid gap-3 rounded-lg border border-border/60 bg-background/45 p-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium text-foreground/80">{`${t.addItem} ${index + 1}`}</p>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => onRemoveItem(section.id, item.id)}
              >
                <Trash2 className="size-4" />
                <span className="sr-only">{`${sectionTitle}: ${t.removeItem} ${index + 1}`}</span>
              </Button>
            </div>

            <div className="grid min-w-0 gap-3 md:grid-cols-2">
              <FormField label={t.fieldLabels.title}>
                <Input
                  value={item.title}
                  className={compactFieldClassName}
                  placeholder={t.placeholders.title}
                  onChange={(event) =>
                    onUpdateItem(section.id, item.id, 'title', event.target.value)
                  }
                />
              </FormField>
              <FormField label={t.fieldLabels.subtitle}>
                <Input
                  value={item.subtitle}
                  className={compactFieldClassName}
                  placeholder={t.placeholders.subtitle}
                  onChange={(event) =>
                    onUpdateItem(section.id, item.id, 'subtitle', event.target.value)
                  }
                />
              </FormField>

              {section.layout === 'timeline' ? (
                <>
                  <FormField label={t.fieldLabels.meta}>
                    <Input
                      value={item.meta}
                      className={compactFieldClassName}
                      placeholder={t.placeholders.meta}
                      onChange={(event) =>
                        onUpdateItem(section.id, item.id, 'meta', event.target.value)
                      }
                    />
                  </FormField>
                  <FormField label={t.fieldLabels.period}>
                    <Input
                      value={item.period}
                      className={compactFieldClassName}
                      placeholder={t.placeholders.period}
                      onChange={(event) =>
                        onUpdateItem(section.id, item.id, 'period', event.target.value)
                      }
                    />
                  </FormField>
                </>
              ) : null}

              <FormField label={t.fieldLabels.description} className="md:col-span-2">
                <Textarea
                  rows={2}
                  value={item.description}
                  className={`${compactFieldClassName} min-h-16 resize-y`}
                  placeholder={t.placeholders.description}
                  onChange={(event) =>
                    onUpdateItem(section.id, item.id, 'description', event.target.value)
                  }
                />
              </FormField>

              {section.layout === 'timeline' ? (
                <div className="grid min-w-0 gap-2 md:col-span-2">
                  <span className="break-words text-xs font-medium leading-tight text-muted-foreground">
                    {t.fieldLabels.highlights}
                  </span>
                  <Suspense fallback={<RichHighlightsEditorSkeleton />}>
                    <RichHighlightsEditor
                      t={t}
                      value={item.highlights}
                      onChange={(value) => onUpdateHighlights(section.id, item.id, value)}
                    />
                  </Suspense>
                </div>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </EditorCardShell>
  )
}
