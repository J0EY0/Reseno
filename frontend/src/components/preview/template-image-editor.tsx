import { Resizable, type ResizeDirection } from "re-resizable";
import { useRef, useState, type PointerEvent, type ReactNode } from "react";

import {
  getTemplateImageResizeLimits,
  moveTemplateImageFrame,
  resizeTemplateImageFrame,
  type TemplateImageGeometry,
} from "@/lib/template-image-geometry";
import type { ResumeTemplateImageElement } from "@/types/resume";

import "./template-image-editor.css";

const PX_PER_MM = 96 / 25.4;
const directions = [
  "top",
  "right",
  "bottom",
  "left",
  "topRight",
  "bottomRight",
  "bottomLeft",
  "topLeft",
] as const;
const handleComponents = Object.fromEntries(
  directions.map((direction) => [
    direction,
    <span
      key={direction}
      data-template-image-resize-handle={direction}
      aria-hidden="true"
    />,
  ]),
);
const handleClasses = Object.fromEntries(
  directions.map((direction) => [
    direction,
    `template-image-resize-handle template-image-resize-${direction}`,
  ]),
);
const handleStyles = {
  top: { height: 8, top: -4, cursor: "ns-resize" },
  bottom: { height: 8, bottom: -4, cursor: "ns-resize" },
  left: { width: 8, left: -4, cursor: "ew-resize" },
  right: { width: 8, right: -4, cursor: "ew-resize" },
  topLeft: { width: 12, height: 12, top: -6, left: -6 },
  topRight: { width: 12, height: 12, top: -6, right: -6 },
  bottomLeft: { width: 12, height: 12, bottom: -6, left: -6 },
  bottomRight: { width: 12, height: 12, bottom: -6, right: -6 },
};

type ResizeSession = {
  frame: TemplateImageGeometry;
  direction: ResizeDirection;
  scale: number;
  clientX: number;
  clientY: number;
};

function pagePixelsPerMm(element: HTMLElement) {
  return (
    element.closest('[data-export-root="resume-page"]')!.getBoundingClientRect()
      .width / 210
  );
}

export default function TemplateImageEditor({
  image,
  children,
  onChange,
}: {
  image: ResumeTemplateImageElement;
  children: ReactNode;
  onChange: (imageId: string, geometry: TemplateImageGeometry) => void;
}) {
  const resizable = useRef<Resizable>(null);
  const drag = useRef<{
    frame: TemplateImageGeometry;
    pointerId: number;
    clientX: number;
    clientY: number;
    pxPerMm: number;
  } | null>(null);
  const [resize, setResize] = useState<ResizeSession | null>(null);
  const limits = getTemplateImageResizeLimits(
    resize?.frame ?? image,
    resize?.direction ?? "bottomRight",
  );

  function move(event: PointerEvent<HTMLDivElement>) {
    const session = drag.current;
    if (!session || session.pointerId !== event.pointerId) return;
    event.preventDefault();
    onChange(image.id, {
      ...moveTemplateImageFrame(session.frame, {
        x:
          session.frame.x + (event.clientX - session.clientX) / session.pxPerMm,
        y:
          session.frame.y + (event.clientY - session.clientY) / session.pxPerMm,
      }),
      width: session.frame.width,
      height: session.frame.height,
    });
  }

  function endDrag(event: PointerEvent<HTMLDivElement>) {
    if (drag.current?.pointerId !== event.pointerId) return;
    drag.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  }

  return (
    <div
      data-template-image-frame="true"
      data-resizing={Boolean(resize) || undefined}
      className="template-image-editable absolute pointer-events-auto touch-none"
      style={{
        left: `${image.x}mm`,
        top: `${image.y}mm`,
        width: `${image.width}mm`,
        height: `${image.height}mm`,
      }}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.stopPropagation();
        if ((event.target as Element).closest(".template-image-resize-handles"))
          return;
        event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = {
          frame: image,
          pointerId: event.pointerId,
          clientX: event.clientX,
          clientY: event.clientY,
          pxPerMm: pagePixelsPerMm(event.currentTarget),
        };
      }}
      onPointerMove={move}
      onPointerUp={endDrag}
      onPointerCancel={(event) => {
        endDrag(event);
        resizable.current?.onMouseUp(event.nativeEvent);
      }}
      onTouchCancel={(event) => resizable.current?.onMouseUp(event.nativeEvent)}
      onLostPointerCapture={() => {
        drag.current = null;
      }}
    >
      <Resizable
        ref={resizable}
        size={{
          width: image.width * PX_PER_MM,
          height: image.height * PX_PER_MM,
        }}
        minWidth={6 * PX_PER_MM}
        minHeight={6 * PX_PER_MM}
        maxWidth={limits.maxWidth * PX_PER_MM}
        maxHeight={limits.maxHeight * PX_PER_MM}
        scale={resize?.scale ?? 1}
        handleWrapperClass="template-image-resize-handles"
        handleStyles={handleStyles}
        handleClasses={handleClasses}
        handleComponent={handleComponents}
        onResizeStart={(event, direction, element) => {
          if ("button" in event && event.button !== 0) return false;
          event.stopPropagation();
          const point = "touches" in event ? event.touches[0] : event;
          setResize({
            frame: image,
            direction,
            scale: pagePixelsPerMm(element) / PX_PER_MM,
            clientX: point.clientX,
            clientY: point.clientY,
          });
        }}
        onResize={(event, direction) => {
          if (!resize) return;
          const point = "touches" in event ? event.touches[0] : event;
          const edge = direction.toLowerCase();
          const pxPerMm = resize.scale * PX_PER_MM;
          const next = resizeTemplateImageFrame(resize.frame, direction, {
            width:
              resize.frame.width +
              ((point.clientX - resize.clientX) / pxPerMm) *
                (edge.includes("left") ? -1 : 1),
            height:
              resize.frame.height +
              ((point.clientY - resize.clientY) / pxPerMm) *
                (edge.includes("top") ? -1 : 1),
          });
          resizable.current?.updateSize({
            width: next.width * PX_PER_MM,
            height: next.height * PX_PER_MM,
          });
          onChange(image.id, next);
        }}
        onResizeStop={() => setResize(null)}
      >
        {children}
      </Resizable>
    </div>
  );
}
