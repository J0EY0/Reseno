import { Resizable } from "re-resizable";
import { useRef, type ReactNode } from "react";

import { ResizeHandle } from "@/components/ui/resize-handle";

export function ResizableWorkspacePanel({
  children,
  className,
  desktop,
  expanded = true,
  width,
  min,
  max,
  direction,
  label,
  onResizeStart,
  onResize,
  onCommit,
  onReset,
}: {
  children: ReactNode;
  className: string;
  desktop: boolean;
  expanded?: boolean;
  width: number;
  min: number;
  max: number;
  direction: "left" | "right";
  label: string;
  onResizeStart: () => void;
  onResize: (width: number) => void;
  onCommit: (width: number) => void;
  onReset: () => void;
}) {
  const separatorRef = useRef<HTMLDivElement>(null);
  const enabled = desktop && expanded;

  return (
    <Resizable
      className={className}
      data-expanded={expanded}
      size={{
        width: desktop ? (expanded ? width : 0) : "100%",
        height: "auto",
      }}
      minWidth={enabled ? min : undefined}
      maxWidth={enabled ? max : undefined}
      style={{ position: desktop ? "sticky" : "relative" }}
      enable={enabled ? { [direction]: true } : false}
      handleStyles={{ [direction]: { zIndex: 30, cursor: "ew-resize" } }}
      handleComponent={{
        [direction]: (
          <ResizeHandle
            separatorRef={separatorRef}
            label={label}
            width={width}
            min={min}
            max={max}
            direction={direction}
            onChange={onCommit}
            onReset={onReset}
          />
        ),
      }}
      onResizeStart={(event) => {
        if (event.type === "mousedown" && event.detail === 2) {
          onReset();
          return false;
        }
        onResizeStart();
      }}
      onResize={(_event, _direction, element) => {
        const nextWidth = element.offsetWidth;
        separatorRef.current?.setAttribute("aria-valuenow", String(nextWidth));
        separatorRef.current?.setAttribute("aria-valuetext", `${nextWidth}px`);
        onResize(nextWidth);
      }}
      onResizeStop={(_event, _direction, element) =>
        onCommit(element.offsetWidth)
      }
    >
      {children}
    </Resizable>
  );
}
