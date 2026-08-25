"use client";

import { cjk } from "@streamdown/cjk";
import { math } from "@streamdown/math";
import { mermaid } from "@streamdown/mermaid";
import type { ComponentProps } from "react";
import { memo } from "react";
import { Streamdown } from "streamdown";

import { cn } from "@/lib/utils";

export type MessageResponseProps = ComponentProps<typeof Streamdown>;

const streamdownPlugins = { cjk, math, mermaid };

export const MessageResponse = memo(
  ({ className, ...props }: MessageResponseProps) => (
    <Streamdown
      className={cn(
        "w-full min-w-0 max-w-full overflow-hidden break-words leading-relaxed [overflow-wrap:anywhere] group-[.is-user]:w-auto group-[.is-user]:overflow-visible [&_*]:max-w-full [&_*]:[overflow-wrap:anywhere] [&>*>pre]:whitespace-pre-wrap [&>*:first-child]:mt-0 [&>*:last-child]:mb-0",
        className,
      )}
      plugins={streamdownPlugins}
      {...props}
    />
  ),
  (prevProps, nextProps) =>
    prevProps.children === nextProps.children &&
    prevProps.components === nextProps.components &&
    nextProps.isAnimating === prevProps.isAnimating,
);

MessageResponse.displayName = "MessageResponse";
