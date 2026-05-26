"use client";

/* eslint-disable react-refresh/only-export-components */

import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import type { DynamicToolUIPart, ToolUIPart } from "ai";
import {
  CheckCircleIcon,
  ChevronDownIcon,
  CircleIcon,
  ClockIcon,
  WrenchIcon,
  XCircleIcon,
} from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
import { isValidElement } from "react";

export type ToolProps = ComponentProps<typeof Collapsible>;

export const Tool = ({ className, ...props }: ToolProps) => (
  <Collapsible
    className={cn(
      "group not-prose mb-1.5 w-full min-w-0 max-w-full overflow-hidden rounded-md border border-border/70 bg-background/60 [contain:layout_paint]",
      className
    )}
    {...props}
  />
);

export type ToolPart = ToolUIPart | DynamicToolUIPart;

export type ToolHeaderProps = {
  title?: string;
  className?: string;
} & (
  | { type: ToolUIPart["type"]; state: ToolUIPart["state"]; toolName?: never }
  | {
      type: DynamicToolUIPart["type"];
      state: DynamicToolUIPart["state"];
      toolName: string;
    }
);

const statusLabels: Record<ToolPart["state"], string> = {
  "approval-requested": "Awaiting Approval",
  "approval-responded": "Responded",
  "input-available": "Running",
  "input-streaming": "Pending",
  "output-available": "Completed",
  "output-denied": "Denied",
  "output-error": "Error",
};

const statusIcons: Record<ToolPart["state"], ReactNode> = {
  "approval-requested": <ClockIcon className="size-3.5 text-yellow-600" />,
  "approval-responded": <CheckCircleIcon className="size-3.5 text-blue-600" />,
  "input-available": <ClockIcon className="size-3.5 animate-pulse" />,
  "input-streaming": <CircleIcon className="size-3.5" />,
  "output-available": <CheckCircleIcon className="size-3.5 text-green-600" />,
  "output-denied": <XCircleIcon className="size-3.5 text-orange-600" />,
  "output-error": <XCircleIcon className="size-3.5 text-red-600" />,
};

export const getStatusBadge = (status: ToolPart["state"]) => (
  <Badge
    className="h-6 shrink-0 gap-1.5 rounded-full px-2 text-[11px]"
    variant="secondary"
  >
    {statusIcons[status]}
    {statusLabels[status]}
  </Badge>
);

export const ToolHeader = ({
  className,
  title,
  type,
  state,
  toolName,
  ...props
}: ToolHeaderProps) => {
  const derivedName =
    type === "dynamic-tool" ? toolName : type.split("-").slice(1).join("-");

  return (
    <CollapsibleTrigger
      className={cn(
        "flex min-h-9 w-full min-w-0 max-w-full items-center justify-between gap-2.5 px-2.5 py-1.5 text-left",
        className
      )}
      {...props}
    >
      <div className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden text-left">
        <WrenchIcon className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate text-left text-xs font-medium">
          {title ?? derivedName}
        </span>
        {getStatusBadge(state)}
      </div>
      <ChevronDownIcon className="size-3.5 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
    </CollapsibleTrigger>
  );
};

export type ToolContentProps = ComponentProps<typeof CollapsibleContent>;

export const ToolContent = ({ className, ...props }: ToolContentProps) => (
  <CollapsibleContent
    className={cn(
      "data-[state=closed]:fade-out-0 data-[state=closed]:slide-out-to-top-2 data-[state=open]:slide-in-from-top-2 min-w-0 max-w-full overflow-hidden text-popover-foreground outline-none data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=open]:max-h-[180px] data-[state=open]:overflow-y-auto data-[state=open]:overscroll-contain data-[state=open]:[scrollbar-width:none] data-[state=open]:[&::-webkit-scrollbar]:hidden",
      className
    )}
    {...props}
  />
);

export type ToolInputProps = ComponentProps<"div"> & {
  input: ToolPart["input"];
};

export const ToolInput = ({ className, input, ...props }: ToolInputProps) => (
  <div
    className={cn("min-w-0 max-w-full space-y-2 overflow-hidden", className)}
    {...props}
  >
    <h4 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">
      Parameters
    </h4>
    <pre className="max-h-28 min-w-0 max-w-full overflow-x-hidden overflow-y-auto whitespace-pre-wrap break-all rounded-md border border-border/60 bg-muted/45 p-3 text-left font-mono text-[11px] leading-5 text-muted-foreground [overflow-wrap:anywhere] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      {JSON.stringify(input, null, 2)}
    </pre>
  </div>
);

export type ToolOutputProps = ComponentProps<"div"> & {
  output: ToolPart["output"];
  errorText: ToolPart["errorText"];
};

export const ToolOutput = ({
  className,
  output,
  errorText,
  ...props
}: ToolOutputProps) => {
  if (!(output || errorText)) {
    return null;
  }

  let Output = (
    <div className="min-w-0 max-w-full overflow-hidden">
      {output as ReactNode}
    </div>
  );

  if (typeof output === "object" && !isValidElement(output)) {
    Output = <ToolTextBlock>{JSON.stringify(output, null, 2)}</ToolTextBlock>;
  } else if (typeof output === "string") {
    Output = <ToolTextBlock>{output}</ToolTextBlock>;
  }

  return (
    <div className={cn("min-w-0 max-w-full space-y-2", className)} {...props}>
      <h4 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">
        {errorText ? "Error" : "Result"}
      </h4>
      <div
        className={cn(
          "min-w-0 max-w-full overflow-hidden rounded-md text-xs break-words [overflow-wrap:anywhere] [&_*]:max-w-full [&_*]:min-w-0 [&_*]:[overflow-wrap:anywhere] [&_code]:whitespace-pre-wrap [&_pre]:whitespace-pre-wrap [&_pre]:break-words [&_table]:w-full",
          errorText
            ? "bg-destructive/10 text-destructive"
            : "bg-muted/50 text-foreground"
        )}
      >
        {errorText && <ToolTextBlock>{errorText}</ToolTextBlock>}
        {Output}
      </div>
    </div>
  );
};

const ToolTextBlock = ({ children }: { children: ReactNode }) => (
  <div className="max-h-28 min-w-0 max-w-full overflow-x-hidden overflow-y-auto whitespace-pre-wrap break-all rounded-md border border-border/60 bg-background/60 p-3 text-left font-mono text-[11px] leading-5 text-foreground [overflow-wrap:anywhere] [scrollbar-width:thin]">
    {children}
  </div>
);
