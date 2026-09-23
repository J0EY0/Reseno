import { useState } from "react";

import { Field, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AppMessages } from "@/i18n";
import type { DocumentLocale } from "@/types/resume";

export function TemplateLocaleSelect({
  disabled,
  chineseLabel,
  englishLabel,
  messages,
  value,
  onValueChange,
}: {
  disabled: boolean;
  chineseLabel: string;
  englishLabel: string;
  messages: AppMessages;
  value: DocumentLocale;
  onValueChange: (locale: DocumentLocale) => void;
}) {
  const [pointerFocus, setPointerFocus] = useState(false);

  return (
    <Field orientation="horizontal" className="w-auto gap-0">
      <FieldLabel htmlFor="template-resume-language" className="sr-only">
        {messages.resumeLanguage}
      </FieldLabel>
      <Select
        disabled={disabled}
        value={value}
        onValueChange={(nextValue) =>
          onValueChange(nextValue as DocumentLocale)
        }
      >
        <SelectTrigger
          id="template-resume-language"
          className="min-w-32 bg-background font-medium"
          aria-label={messages.resumeLanguage}
          data-pointer-focus={pointerFocus || undefined}
          onBlur={() => setPointerFocus(false)}
          onKeyDownCapture={() => setPointerFocus(false)}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent
          position="popper"
          align="start"
          className="w-max min-w-[max(10rem,var(--radix-select-trigger-width))] [&_[data-slot=select-item]]:whitespace-nowrap"
          onPointerUpCapture={() => setPointerFocus(true)}
          onPointerDownOutside={() => setPointerFocus(true)}
          onKeyDownCapture={() => setPointerFocus(false)}
        >
          <SelectGroup>
            <SelectItem value="zh">{chineseLabel}</SelectItem>
            <SelectItem value="en">{englishLabel}</SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>
    </Field>
  );
}
