import { lazy, Suspense, useState } from "react";

import type { AppMessages } from "@/i18n";
import { getInlineTextHtml } from "@/lib/rich-text";
import { cn } from "@/lib/utils";

const InlineTextEditor = lazy(() => import("./inline-text-editor"));

export type InlineTextInputProps = {
  id?: string;
  autoFocus?: boolean;
  "aria-label": string;
  className?: string;
  multiline?: boolean;
  placeholder?: string;
  t: AppMessages;
  value: string;
  onChange: (value: string) => void;
};

export function InlineTextInput(props: InlineTextInputProps) {
  const { autoFocus = false, ...editorProps } = props;
  const { className, multiline, value } = props;
  const [autoFocusFrom] = useState(() =>
    autoFocus ? document.activeElement : undefined,
  );
  return (
    <Suspense
      fallback={
        <div
          className={cn(
            "rich-text-editor w-full min-w-0 rounded-md border border-input bg-transparent px-3 py-1 text-base shadow-xs md:text-sm",
            multiline
              ? "min-h-16 py-2"
              : "flex h-9 items-center overflow-hidden",
            className,
          )}
          aria-hidden="true"
          dangerouslySetInnerHTML={{
            __html: getInlineTextHtml(value) || "&nbsp;",
          }}
        />
      }
    >
      <InlineTextEditor {...editorProps} autoFocusFrom={autoFocusFrom} />
    </Suspense>
  );
}
