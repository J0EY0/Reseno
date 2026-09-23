import { Resizable } from "re-resizable";
import { useEffect, useRef } from "react";

import { ResizeHandle } from "@/components/ui/resize-handle";

export default function WorkspacePanelResizer({
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
  const resizableRef = useRef<Resizable>(null);
  const activeResize = useRef<{
    width: number;
    commit: typeof onCommit;
  } | null>(null);

  useEffect(() => {
    const cancel = (event: TouchEvent) =>
      resizableRef.current?.onMouseUp(event);
    window.addEventListener("touchcancel", cancel);
    return () => {
      window.removeEventListener("touchcancel", cancel);
      const active = activeResize.current;
      activeResize.current = null;
      active?.commit(active.width);
    };
  }, []);

  return (
    <Resizable
      ref={resizableRef}
      size={{ width, height: "100%" }}
      minWidth={min}
      maxWidth={max}
      style={{ position: "absolute", top: 0, left: 0, pointerEvents: "none" }}
      enable={{ [direction]: true }}
      handleStyles={{
        [direction]: { zIndex: 30, cursor: "ew-resize", pointerEvents: "auto" },
      }}
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
        activeResize.current = { width, commit: onCommit };
        onResizeStart();
      }}
      onResize={(_event, _direction, element) => {
        const nextWidth = element.offsetWidth;
        if (activeResize.current) activeResize.current.width = nextWidth;
        separatorRef.current?.setAttribute("aria-valuenow", String(nextWidth));
        separatorRef.current?.setAttribute("aria-valuetext", `${nextWidth}px`);
        onResize(nextWidth);
      }}
      onResizeStop={(_event, _direction, element) => {
        activeResize.current = null;
        onCommit(element.offsetWidth);
      }}
    />
  );
}
