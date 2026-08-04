import {
  ArrowDown,
  ArrowUp,
  Award,
  Briefcase,
  FolderKanban,
  GraduationCap,
  List,
  Plus,
  Trash2,
  type LucideIcon,
} from 'lucide-react'

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
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { AppMessages } from '@/i18n'
import type { ResumeSectionMutation } from '@/lib/resume-sections'
import type { ResumeSection, SectionKind } from '@/types/resume'

import { EditorCardShell } from './editor-card-shell'
import { FormField } from './form-field'
import { ResumeSectionItemsEditor } from './resume-section-editors'

const sectionIcons: Record<SectionKind, LucideIcon> = {
  education: GraduationCap,
  experience: Briefcase,
  project: FolderKanban,
  achievement: Award,
  simple_list: List,
}

const compactFieldClassName =
  'border-border/60 bg-muted/35 shadow-none focus-visible:border-ring/50 focus-visible:ring-1 focus-visible:ring-ring/20'

export type ResumeSectionCardProps = {
  t: AppMessages
  section: ResumeSection
  collapsed: boolean
  onToggle: () => void
  onMutation: (mutation: ResumeSectionMutation) => void
  onRemoveSection: (sectionId: string) => void
  onMoveSectionUp: (sectionId: string) => void
  onMoveSectionDown: (sectionId: string) => void
  canMoveUp: boolean
  canMoveDown: boolean
}

export function ResumeSectionCard({
  t,
  section,
  collapsed,
  onToggle,
  onMutation,
  onRemoveSection,
  onMoveSectionDown,
  onMoveSectionUp,
  canMoveUp,
  canMoveDown,
}: ResumeSectionCardProps) {
  const Icon = sectionIcons[section.kind]
  const sectionTitle = section.title.trim() || t.sectionTitles[section.kind]
  const itemLabel = section.items.length === 1 ? t.itemCountSingular : t.itemCount
  const itemCountLabel = `${section.items.length} ${itemLabel}`

  return (
    <EditorCardShell
      icon={Icon}
      title={sectionTitle}
      titleMeta={itemCountLabel}
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
            aria-label={`${sectionTitle}: ${t.moveSectionUp}`}
            onClick={() => onMoveSectionUp(section.id)}
          >
            <ArrowUp aria-hidden="true" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            disabled={!canMoveDown}
            aria-label={`${sectionTitle}: ${t.moveSectionDown}`}
            onClick={() => onMoveSectionDown(section.id)}
          >
            <ArrowDown aria-hidden="true" />
          </Button>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`${sectionTitle}: ${t.deleteSection}`}
                onClick={(event) => event.stopPropagation()}
              >
                <Trash2 aria-hidden="true" />
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent size="sm">
              <AlertDialogHeader>
                <AlertDialogTitle>{t.confirmDeleteSectionTitle}</AlertDialogTitle>
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
            value={section.title}
            className={compactFieldClassName}
            placeholder={t.placeholders.sectionName}
            onChange={(event) =>
              onMutation({
                type: 'section.rename',
                sectionId: section.id,
                title: event.target.value,
              })
            }
          />
        </FormField>

        {section.kind !== 'simple_list' ? (
          <Button
            type="button"
            variant="outline"
            className="self-start"
            onClick={() =>
              onMutation({ type: 'item.add', sectionId: section.id })
            }
          >
            <Plus aria-hidden="true" data-icon="inline-start" />
            {t.addItem}
          </Button>
        ) : null}
      </div>

      <div className="grid gap-3">
        <ResumeSectionItemsEditor
          t={t}
          section={section}
          onMutation={onMutation}
        />
      </div>
    </EditorCardShell>
  )
}
