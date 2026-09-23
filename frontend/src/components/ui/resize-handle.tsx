import type { Ref } from "react";

import "./resize-handle.css";

export function ResizeHandle({
  label,
  width,
  min,
  max,
  direction,
  separatorRef,
  onChange,
  onReset,
}: {
  label: string;
  width: number;
  min: number;
  max: number;
  direction: "left" | "right";
  separatorRef: Ref<HTMLDivElement>;
  onChange: (width: number) => void;
  onReset: () => void;
}) {
  const applyWidth = (value: number) =>
    onChange(Math.round(Math.min(max, Math.max(min, value))));

  const move = (sign: number, accelerated: boolean) =>
    applyWidth(
      width + sign * (accelerated ? 64 : 16) * (direction === "right" ? 1 : -1),
    );
  return (
    <div
      ref={separatorRef}
      role="separator"
      tabIndex={0}
      aria-label={label}
      aria-orientation="vertical"
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={width}
      aria-valuetext={`${width}px`}
      className="workspace-resize-separator relative h-full cursor-ew-resize touch-none outline-none"
      onDoubleClick={onReset}
      onKeyDown={(event) => {
        if (event.key === "Home" || event.key === "End") {
          event.preventDefault();
          applyWidth(event.key === "Home" ? min : max);
        } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
          event.preventDefault();
          move(event.key === "ArrowRight" ? 1 : -1, event.shiftKey);
        }
      }}
    />
  );
}
