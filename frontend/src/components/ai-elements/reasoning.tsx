"use client";

/* eslint-disable react-refresh/only-export-components */

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { cjk } from "@streamdown/cjk";
import { math } from "@streamdown/math";
import { mermaid } from "@streamdown/mermaid";
import { ChevronDownIcon, CircleIcon } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentProps,
  type ReactNode,
} from "react";
import { Streamdown } from "streamdown";

interface ReasoningContextValue {
  duration: number | undefined;
  isOpen: boolean;
  isStreaming: boolean;
  setIsOpen: (open: boolean) => void;
}

const ReasoningContext = createContext<ReasoningContextValue | null>(null);
const streamdownPlugins = { cjk, math, mermaid };
const reasoningLinkSafety = { enabled: false };

export function useReasoning() {
  const context = useContext(ReasoningContext);

  if (!context) {
    throw new Error("Reasoning components must be used within Reasoning.");
  }

  return context;
}

export type ReasoningProps = ComponentProps<typeof Collapsible> & {
  duration?: number;
  isStreaming?: boolean;
};

export const Reasoning = ({
  className,
  defaultOpen = false,
  duration,
  isStreaming = false,
  onOpenChange,
  open,
  ...props
}: ReasoningProps) => {
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const [elapsed, setElapsed] = useState(0);
  const startedAtRef = useRef(0);
  const isOpen = open ?? (isStreaming || internalOpen);

  const setIsOpen = useCallback(
    (nextOpen: boolean) => {
      setInternalOpen(nextOpen);
      onOpenChange?.(nextOpen);
    },
    [onOpenChange],
  );

  useEffect(() => {
    if (!isStreaming) {
      return;
    }

    startedAtRef.current = Date.now();
    const timer = window.setInterval(() => {
      setElapsed(
        Math.max(1, Math.round((Date.now() - startedAtRef.current) / 1000)),
      );
    }, 1000);

    return () => window.clearInterval(timer);
  }, [isStreaming]);

  const visibleDuration =
    duration ?? (!isStreaming && elapsed > 0 ? elapsed : undefined);
  const contextValue = useMemo(
    () => ({
      duration: visibleDuration,
      isOpen,
      isStreaming,
      setIsOpen,
    }),
    [isOpen, isStreaming, setIsOpen, visibleDuration],
  );

  return (
    <ReasoningContext.Provider value={contextValue}>
      <Collapsible
        className={cn("not-prose w-full min-w-0 text-sm", className)}
        onOpenChange={setIsOpen}
        open={isOpen}
        {...props}
      />
    </ReasoningContext.Provider>
  );
};

export type ReasoningTriggerProps = ComponentProps<typeof CollapsibleTrigger> & {
  getThinkingMessage?: (
    isStreaming: boolean,
    duration?: number,
  ) => ReactNode;
};

export const ReasoningTrigger = ({
  className,
  getThinkingMessage,
  ...props
}: ReasoningTriggerProps) => {
  const { duration, isStreaming } = useReasoning();
  const message =
    getThinkingMessage?.(isStreaming, duration) ??
    (isStreaming
      ? "Thinking..."
      : duration
        ? `Thought for ${duration}s`
        : "Reasoning");

  return (
    <CollapsibleTrigger
      className={cn(
        "group flex w-full min-w-0 items-center gap-2 rounded-md py-1 text-left text-xs text-muted-foreground",
        className,
      )}
      {...props}
    >
      <CircleIcon
        className={cn(
          "size-2.5 shrink-0 fill-current",
          isStreaming && "animate-pulse",
        )}
      />
      <span className="min-w-0 flex-1 truncate">{message}</span>
      <ChevronDownIcon className="size-3.5 shrink-0 transition-transform group-data-[state=open]:rotate-180" />
    </CollapsibleTrigger>
  );
};

export type ReasoningContentProps = ComponentProps<typeof CollapsibleContent> & {
  children: string;
};

export const ReasoningContent = ({
  children,
  className,
  ...props
}: ReasoningContentProps) => (
  <CollapsibleContent
    className={cn(
      "data-[state=closed]:fade-out-0 data-[state=closed]:slide-out-to-top-1 data-[state=open]:slide-in-from-top-1 overflow-hidden outline-none data-[state=closed]:animate-out data-[state=open]:animate-in",
      className,
    )}
    {...props}
  >
    <Streamdown
      className="mt-2 max-h-48 min-w-0 max-w-full overflow-x-hidden overflow-y-auto whitespace-pre-wrap break-words rounded-md border border-border/60 bg-muted/25 px-3 py-2 text-xs leading-5 text-muted-foreground [overflow-wrap:anywhere] [scrollbar-width:none] [&_*]:max-w-full [&_*]:[overflow-wrap:anywhere] [&_a]:break-all [&_a]:text-current [&_a]:underline-offset-2 [&::-webkit-scrollbar]:hidden"
      linkSafety={reasoningLinkSafety}
      plugins={streamdownPlugins}
    >
      {children}
    </Streamdown>
  </CollapsibleContent>
);
