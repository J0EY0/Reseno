import { Trash2, Upload, UserRound } from 'lucide-react'
import type { ChangeEvent } from 'react'

import type { AppMessages } from '@/i18n'
import { getInitials } from '@/lib/resume'
import type { CustomField, ResumeBasicInfo } from '@/types/resume'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

import { EditorCardShell } from './editor-card-shell'
import { FormField } from './form-field'

export function BasicInfoCard({
  t,
  basic,
  collapsed,
  onToggle,
  onUpdateBasic,
  onUpdateCustomField,
  onAddCustomField,
  onRemoveCustomField,
  onAvatarUpload,
  onRemoveAvatar,
}: {
  t: AppMessages
  basic: ResumeBasicInfo
  collapsed: boolean
  onToggle: () => void
  onUpdateBasic: <K extends keyof ResumeBasicInfo>(
    field: K,
    value: ResumeBasicInfo[K],
  ) => void
  onUpdateCustomField: (
    id: string,
    field: keyof Omit<CustomField, 'id'>,
    value: string,
  ) => void
  onAddCustomField: () => void
  onRemoveCustomField: (id: string) => void
  onAvatarUpload: (event: ChangeEvent<HTMLInputElement>) => void
  onRemoveAvatar: () => void
}) {
  const hasAvatar = Boolean(basic.avatar.trim())

  return (
    <EditorCardShell
      icon={UserRound}
      title={t.basicInfo}
      summary={t.basicSummary}
      toggleLabel={`${t.basicInfo}: ${t.toggleSection}`}
      collapsed={collapsed}
      onToggle={onToggle}
    >
      <div className="grid gap-5 lg:grid-cols-[144px_minmax(0,1fr)]">
        <div className="grid content-start gap-3 self-start">
          <div className="relative">
            <div className="flex aspect-[4/5] items-center justify-center overflow-hidden rounded-2xl border border-border bg-gradient-to-br from-primary/12 to-amber-200/30 text-2xl font-semibold text-primary">
              {hasAvatar ? (
                <img src={basic.avatar} alt={basic.name} className="size-full object-cover" />
              ) : (
                <span>{getInitials(basic.name)}</span>
              )}
            </div>
            {hasAvatar ? (
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="absolute -right-2 -top-2 z-10 size-8 rounded-full border-border/80 bg-background shadow-sm"
                onClick={onRemoveAvatar}
              >
                <Trash2 className="size-3.5" />
                <span className="sr-only">{t.removeAvatar}</span>
              </Button>
            ) : null}
          </div>
          <label className="inline-flex w-full cursor-pointer self-start">
            <Button
              type="button"
              variant="outline"
              className="h-auto w-full whitespace-normal px-3 py-3 text-center leading-tight"
              asChild
            >
              <span className="flex min-h-14 flex-col items-center justify-center gap-1.5">
                <Upload className="size-4" />
                {t.uploadAvatar}
              </span>
            </Button>
            <input type="file" accept="image/*" hidden onChange={onAvatarUpload} />
          </label>
        </div>

        <div className="grid min-w-0 gap-3 [grid-template-columns:repeat(auto-fit,minmax(180px,1fr))]">
          <FormField label={t.fieldLabels.name}>
            <Input
              name="name"
              autoComplete="name"
              value={basic.name}
              onChange={(event) => onUpdateBasic('name', event.target.value)}
            />
          </FormField>
          <FormField label={t.fieldLabels.headline}>
            <Input
              name="headline"
              autoComplete="organization-title"
              value={basic.headline}
              onChange={(event) => onUpdateBasic('headline', event.target.value)}
            />
          </FormField>
          <FormField label={t.fieldLabels.phone}>
            <Input
              name="phone"
              type="tel"
              autoComplete="tel"
              value={basic.phone}
              onChange={(event) => onUpdateBasic('phone', event.target.value)}
            />
          </FormField>
          <FormField label={t.fieldLabels.email}>
            <Input
              name="email"
              type="email"
              autoComplete="email"
              value={basic.email}
              onChange={(event) => onUpdateBasic('email', event.target.value)}
            />
          </FormField>
          <FormField label={t.fieldLabels.location}>
            <Input
              name="location"
              autoComplete="address-level2"
              value={basic.location}
              onChange={(event) => onUpdateBasic('location', event.target.value)}
            />
          </FormField>
          <FormField label={t.fieldLabels.summary} className="[grid-column:1/-1]">
            <Textarea
              rows={4}
              value={basic.summary}
              placeholder={t.placeholders.summary}
              onChange={(event) => onUpdateBasic('summary', event.target.value)}
            />
          </FormField>
        </div>
      </div>

      <div className="flex items-center justify-between gap-4">
        <p className="text-xs font-medium text-muted-foreground">
          {t.customFields}
        </p>
        <Button type="button" variant="outline" size="sm" onClick={onAddCustomField}>
          {t.addField}
        </Button>
      </div>

      <div className="grid gap-3">
        {basic.customFields.map((field) => (
          <div
            key={field.id}
            className="grid gap-3 rounded-xl border border-border/70 bg-muted/40 p-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]"
          >
            <FormField label={t.fieldLabels.fieldName}>
              <Input
                value={field.label}
                onChange={(event) =>
                  onUpdateCustomField(field.id, 'label', event.target.value)
                }
              />
            </FormField>
            <FormField label={t.fieldLabels.fieldValue}>
              <Input
                value={field.value}
                onChange={(event) =>
                  onUpdateCustomField(field.id, 'value', event.target.value)
                }
              />
            </FormField>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="self-end"
              onClick={() => onRemoveCustomField(field.id)}
            >
              <span className="sr-only">{t.removeField}</span>
              ×
            </Button>
          </div>
        ))}
      </div>
    </EditorCardShell>
  )
}
