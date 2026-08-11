import { lazy, Suspense } from "react";

import type { MessageResponseProps } from "@/components/ai-elements/message-response";

const AGENT_MARKDOWN_CLASSNAME =
  "[&_h1]:!mb-2 [&_h1]:!mt-3 [&_h1]:!text-base [&_h1]:!font-semibold [&_h1]:!leading-7 [&_h1]:!tracking-normal [&_h2]:!mb-2 [&_h2]:!mt-3 [&_h2]:!text-base [&_h2]:!font-semibold [&_h2]:!leading-7 [&_h2]:!tracking-normal [&_h3]:!mb-1.5 [&_h3]:!mt-2.5 [&_h3]:!text-sm [&_h3]:!font-semibold [&_h3]:!leading-6";

const RichMessageResponse = lazy(() =>
  import("@/components/ai-elements/message-response").then((module) => ({
    default: module.MessageResponse,
  })),
);

export function AgentPlainResponse({ text }: { text: string }) {
  return (
    <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">
      {text}
    </p>
  );
}

export function AgentRichResponse({
  fallbackText,
  text,
  ...props
}: {
  fallbackText?: string;
  text: string;
} & Omit<MessageResponseProps, "children">) {
  return (
    <Suspense fallback={<AgentPlainResponse text={fallbackText ?? text} />}>
      <RichMessageResponse className={AGENT_MARKDOWN_CLASSNAME} {...props}>
        {text}
      </RichMessageResponse>
    </Suspense>
  );
}
