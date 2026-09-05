import type { MessageResponseProps } from "@/components/ai-elements/message-response";
import { cn } from "@/lib/utils";
import { lazy, Suspense } from "react";

const AGENT_MARKDOWN_CLASSNAME =
  "[&_h1]:!mb-2 [&_h1]:!mt-3 [&_h1]:!text-base [&_h1]:!font-semibold [&_h1]:!leading-7 [&_h1]:!tracking-normal [&_h2]:!mb-2 [&_h2]:!mt-3 [&_h2]:!text-base [&_h2]:!font-semibold [&_h2]:!leading-7 [&_h2]:!tracking-normal [&_h3]:!mb-1.5 [&_h3]:!mt-2.5 [&_h3]:!text-sm [&_h3]:!font-semibold [&_h3]:!leading-6";
const AGENT_STREAM_ANIMATION = {
  animation: "fadeIn",
  duration: 120,
  easing: "ease-out",
  sep: "char",
  stagger: 8,
} as const;

const richMessageResponsePromise = import(
  "@/components/ai-elements/message-response"
).then((module) => ({
    default: module.MessageResponse,
  }));
const RichMessageResponse = lazy(() => richMessageResponsePromise);

export function AgentPlainResponse({
  className,
  inlineTail = false,
  text,
}: {
  className?: string;
  inlineTail?: boolean;
  text: string;
}) {
  return (
    <p
      className={cn(
        "whitespace-pre-wrap break-words text-sm leading-relaxed",
        inlineTail && "inline",
        className,
      )}
    >
      {text}
    </p>
  );
}

export function AgentRichResponse({
  className,
  fallbackText,
  inlineTail = false,
  isStreaming = false,
  text,
  ...props
}: {
  fallbackText?: string;
  inlineTail?: boolean;
  isStreaming?: boolean;
  text: string;
} & Omit<
    MessageResponseProps,
    "animated" | "children" | "isAnimating" | "mode"
  >) {
  return (
    <Suspense
      fallback={
        <AgentPlainResponse
          className={isStreaming ? "invisible" : undefined}
          inlineTail={inlineTail}
          text={fallbackText ?? text}
        />
      }
    >
      <RichMessageResponse
        animated={isStreaming ? AGENT_STREAM_ANIMATION : false}
        className={cn(
          AGENT_MARKDOWN_CLASSNAME,
          inlineTail && "contents [&>p:last-child]:inline",
          isStreaming && "agent-streaming-response",
          className,
        )}
        isAnimating={isStreaming}
        mode={isStreaming ? "streaming" : "static"}
        {...props}
      >
        {text}
      </RichMessageResponse>
    </Suspense>
  );
}
