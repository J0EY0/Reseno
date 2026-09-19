import { Suspense, lazy } from "react";

import { Field } from "@/components/ui/field";
import type { AppMessages } from "@/i18n";
import { isRichTextEmpty } from "@/lib/rich-text";

import { RichHighlightsEditorSkeleton } from "./rich-highlights-editor-skeleton";

const RichHighlightsEditor = lazy(() =>
  import("./rich-highlights-editor").then((module) => ({
    default: module.RichHighlightsEditor,
  })),
);

export const compactResumeFieldClassName =
  "resume-editor-field rounded-md border border-border px-3 shadow-none focus-visible:ring-0";

export function HighlightsField({
  t,
  value,
  onChange,
}: {
  t: AppMessages;
  value: string[];
  onChange: (value: string[]) => void;
}) {
  return (
    <Field className="min-w-0 gap-0 [grid-column:1/-1]">
      <Suspense
        fallback={
          <RichHighlightsEditorSkeleton
            label={t.fieldLabels.highlights}
            value={value}
          />
        }
      >
        <RichHighlightsEditor
          t={t}
          label={t.fieldLabels.highlights}
          value={value}
          placeholder={t.placeholders.highlightItem}
          onChange={(nextValue) =>
            onChange(isRichTextEmpty(nextValue) ? [] : [nextValue])
          }
        />
      </Suspense>
    </Field>
  );
}

export function SimpleContentField({
  t,
  value,
  onChange,
}: {
  t: AppMessages;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <Field className="min-w-0 gap-0">
      <Suspense
        fallback={
          <RichHighlightsEditorSkeleton
            label={t.fieldLabels.content}
            value={isRichTextEmpty(value) ? [] : [value]}
          />
        }
      >
        <RichHighlightsEditor
          t={t}
          label={t.fieldLabels.content}
          value={isRichTextEmpty(value) ? [] : [value]}
          placeholder={t.placeholders.content}
          onChange={onChange}
        />
      </Suspense>
    </Field>
  );
}
