import type { AppMessages } from "@/i18n";
import type { DocumentLocale } from "@/types/resume";

import { TemplateLocaleSelect } from "./template-locale-select";

export function TemplatePreviewToolbar({
  messages,
  templateLocale,
  disabled,
  onTemplateLocaleChange,
}: {
  messages: AppMessages;
  templateLocale: DocumentLocale;
  disabled: boolean;
  onTemplateLocaleChange: (locale: DocumentLocale) => void;
}) {
  return (
    <div
      data-slot="template-preview-toolbar"
      className="absolute top-3 left-4 z-10 print:hidden sm:left-6 [&_[data-slot=select-trigger]:hover]:bg-transparent [&_[data-slot=select-trigger]:hover]:text-foreground [&_[data-slot=select-trigger][data-pointer-focus]]:ring-0 [&_[data-slot=select-trigger]]:h-8 [&_[data-slot=select-trigger]]:min-w-0 [&_[data-slot=select-trigger]]:border-transparent [&_[data-slot=select-trigger]]:bg-transparent [&_[data-slot=select-trigger]]:text-xs [&_[data-slot=select-trigger]]:font-normal [&_[data-slot=select-trigger]]:text-muted-foreground [&_[data-slot=select-trigger]]:shadow-none"
    >
      <TemplateLocaleSelect
        disabled={disabled}
        chineseLabel={messages.chinesePreview}
        englishLabel={messages.englishPreview}
        messages={messages}
        value={templateLocale}
        onValueChange={onTemplateLocaleChange}
      />
    </div>
  );
}
