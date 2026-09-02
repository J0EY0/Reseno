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
  return (
    <Field orientation="horizontal" className="w-auto gap-0">
      <FieldLabel
        htmlFor="template-resume-language"
        className="sr-only"
      >
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
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent position="popper">
          <SelectGroup>
            <SelectItem value="zh">{chineseLabel}</SelectItem>
            <SelectItem value="en">{englishLabel}</SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>
    </Field>
  );
}
