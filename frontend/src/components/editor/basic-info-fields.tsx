import { Trash2, Upload } from "lucide-react";
import type { ChangeEvent } from "react";

import type { AppMessages } from "@/i18n";
import { normalizeContactFieldType } from "@/lib/contact-links";
import { getInitials } from "@/lib/resume";
import { getRichTextPlainText } from "@/lib/rich-text";
import type {
  ContactFieldType,
  CustomField,
  ResumeBasicInfo,
} from "@/types/resume";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { FormField } from "./form-field";
import { InlineTextInput } from "./inline-text-input";
import { compactResumeFieldClassName } from "./resume-section-editor-fields";

export type BasicInfoFieldsProps = {
  t: AppMessages;
  basic: ResumeBasicInfo;
  onUpdateBasic: <K extends keyof ResumeBasicInfo>(
    field: K,
    value: ResumeBasicInfo[K],
  ) => void;
  onUpdateCustomField: <K extends keyof Omit<CustomField, "id">>(
    id: string,
    field: K,
    value: CustomField[K],
  ) => void;
  onAddCustomField: () => void;
  onRemoveCustomField: (id: string) => void;
  onAvatarUpload: (event: ChangeEvent<HTMLInputElement>) => void;
  onRemoveAvatar: () => void;
};

export function BasicInfoFields({
  t,
  basic,
  onUpdateBasic,
  onUpdateCustomField,
  onAddCustomField,
  onRemoveCustomField,
  onAvatarUpload,
  onRemoveAvatar,
}: BasicInfoFieldsProps) {
  const hasAvatar = Boolean(basic.avatar.trim());

  return (
    <>
      <div className="grid gap-4 lg:grid-cols-[112px_minmax(0,1fr)]">
        <div className="grid content-start gap-3 self-start">
          <div className="relative">
            <div className="flex aspect-[4/5] items-center justify-center overflow-hidden rounded-2xl border border-border bg-gradient-to-br from-primary/12 to-amber-200/30 text-2xl font-semibold text-primary">
              {hasAvatar ? (
                <img
                  src={basic.avatar}
                  alt={getRichTextPlainText(basic.name)}
                  className="size-full object-cover"
                />
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
              <span className="flex min-h-12 flex-col items-center justify-center gap-1.5">
                <Upload className="size-4" />
                {t.uploadAvatar}
              </span>
            </Button>
            <input
              type="file"
              accept="image/*"
              hidden
              onChange={onAvatarUpload}
            />
          </label>
        </div>

        <div className="grid min-w-0 gap-3 [grid-template-columns:repeat(auto-fit,minmax(180px,1fr))]">
          <FormField label={t.fieldLabels.name}>
            <InlineTextInput
              className={compactResumeFieldClassName}
              t={t}
              aria-label={t.fieldLabels.name}
              value={basic.name}
              onChange={(value) => onUpdateBasic("name", value)}
            />
          </FormField>
          <FormField label={t.fieldLabels.headline}>
            <InlineTextInput
              className={compactResumeFieldClassName}
              t={t}
              aria-label={t.fieldLabels.headline}
              value={basic.headline}
              onChange={(value) => onUpdateBasic("headline", value)}
            />
          </FormField>
          <FormField label={t.fieldLabels.phone}>
            <Input
              className={compactResumeFieldClassName}
              name="phone"
              type="tel"
              autoComplete="tel"
              value={basic.phone}
              onChange={(event) => onUpdateBasic("phone", event.target.value)}
            />
          </FormField>
          <FormField label={t.fieldLabels.email}>
            <Input
              className={compactResumeFieldClassName}
              name="email"
              type="email"
              autoComplete="email"
              value={basic.email}
              onChange={(event) => onUpdateBasic("email", event.target.value)}
            />
          </FormField>
          <FormField label={t.fieldLabels.location}>
            <InlineTextInput
              className={compactResumeFieldClassName}
              t={t}
              aria-label={t.fieldLabels.location}
              value={basic.location}
              onChange={(value) => onUpdateBasic("location", value)}
            />
          </FormField>
          <FormField
            label={t.fieldLabels.summary}
            className="[grid-column:1/-1]"
          >
            <InlineTextInput
              t={t}
              aria-label={t.fieldLabels.summary}
              multiline
              className={`${compactResumeFieldClassName} min-h-24`}
              placeholder={t.placeholders.summary}
              value={basic.summary}
              onChange={(value) => onUpdateBasic("summary", value)}
            />
          </FormField>
        </div>
      </div>

      <div className="flex items-center justify-between gap-4">
        <p className="text-xs font-medium text-muted-foreground">
          {t.customFields}
        </p>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onAddCustomField}
        >
          {t.addField}
        </Button>
      </div>

      <div className="grid gap-3">
        {basic.customFields.map((field) => (
          <div
            key={field.id}
            className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] gap-4 py-2"
          >
            <FormField label={t.fieldLabels.fieldType}>
              <Select
                value={normalizeContactFieldType(field.type)}
                onValueChange={(value) =>
                  onUpdateCustomField(
                    field.id,
                    "type",
                    normalizeContactFieldType(value),
                  )
                }
              >
                <SelectTrigger
                  className={`w-full ${compactResumeFieldClassName}`}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {(
                      Object.entries(t.contactFieldTypes) as Array<
                        [ContactFieldType, string]
                      >
                    ).map(([value, label]) => (
                      <SelectItem key={value} value={value}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </FormField>
            <FormField label={t.fieldLabels.fieldName}>
              <Input
                className={compactResumeFieldClassName}
                value={field.label}
                onChange={(event) =>
                  onUpdateCustomField(field.id, "label", event.target.value)
                }
              />
            </FormField>
            <FormField
              label={t.fieldLabels.fieldValue}
              className="col-span-2 row-start-2"
            >
              <Input
                className={compactResumeFieldClassName}
                type={
                  field.type === "email"
                    ? "email"
                    : field.type === "phone"
                      ? "tel"
                      : field.type === "url"
                        ? "url"
                        : "text"
                }
                value={field.value}
                onChange={(event) =>
                  onUpdateCustomField(field.id, "value", event.target.value)
                }
              />
            </FormField>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="col-start-3 row-start-2 self-end"
              onClick={() => onRemoveCustomField(field.id)}
            >
              <span className="sr-only">{t.removeField}</span>×
            </Button>
          </div>
        ))}
      </div>
    </>
  );
}
