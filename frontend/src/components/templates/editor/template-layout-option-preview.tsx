import type { ResumeTemplateLayout } from "@/types/resume";

import { dividerStyleValues, type TemplateDividerStyle } from "./layout-values";

type TemplateLayoutOptionPreviewProps =
  | { kind: "basicInfo"; value: ResumeTemplateLayout["basicInfo"] }
  | { kind: "section"; value: ResumeTemplateLayout["section"] }
  | { kind: "timeline"; value: ResumeTemplateLayout["timelineItemLayout"] }
  | { kind: "list"; value: ResumeTemplateLayout["listItemLayout"] }
  | { kind: "divider"; value: TemplateDividerStyle };

function BasicInfoPreview({
  value,
}: {
  value: ResumeTemplateLayout["basicInfo"];
}) {
  if (value === "sidebar") {
    return (
      <g>
        <rect x="4" y="4" width="16" height="24" rx="2" opacity="0.12" />
        <rect x="7" y="8" width="10" height="3" rx="1" />
        <path
          d="M7 15h10M7 20h7M25 9h25M25 16h25M25 23h18"
          stroke="currentColor"
          strokeWidth="2"
          opacity="0.4"
        />
      </g>
    );
  }

  if (value === "split") {
    return (
      <g>
        <rect x="5" y="9" width="16" height="4" rx="1" />
        <path
          d="M5 19h12M30 14h21M36 19h15"
          stroke="currentColor"
          strokeWidth="2"
          opacity="0.4"
        />
      </g>
    );
  }

  const isLeft = value === "left";

  return (
    <g>
      {value === "profile" ? (
        <rect x="4" y="4" width="48" height="24" rx="4" opacity="0.12" />
      ) : null}
      <rect x={isLeft ? 6 : 20} y="7" width="16" height="4" rx="1" />
      <rect
        x={isLeft ? 6 : 15}
        y="16"
        width="26"
        height="2"
        rx="1"
        opacity="0.4"
      />
      <rect
        x={isLeft ? 6 : 10}
        y="23"
        width="36"
        height="2"
        rx="1"
        opacity="0.4"
      />
    </g>
  );
}

function SectionPreview({ value }: { value: ResumeTemplateLayout["section"] }) {
  const isBoxed = value === "boxed";

  return (
    <g>
      {isBoxed ? (
        <g>
          <rect
            x="5"
            y="4"
            width="46"
            height="24"
            fill="none"
            stroke="currentColor"
            opacity="0.4"
          />
          <rect x="5" y="4" width="46" height="10" opacity="0.12" />
          <path d="M5 14h46" stroke="currentColor" opacity="0.4" />
        </g>
      ) : null}
      {value === "band" ? (
        <rect x="5" y="5" width="46" height="10" rx="2" opacity="0.12" />
      ) : null}
      <rect
        x={value === "accent" ? 21 : isBoxed || value === "band" ? 9 : 5}
        y="8"
        width="14"
        height="3"
        rx="1"
      />
      {value === "ruled" ? (
        <path d="M24 10h27" stroke="currentColor" opacity="0.5" />
      ) : null}
      {value === "underlined" ? (
        <path d="M5 15h46" stroke="currentColor" opacity="0.5" />
      ) : null}
      {value === "accent" ? (
        <path d="M5 10h12M39 10h12" stroke="currentColor" opacity="0.5" />
      ) : null}
      <path
        d={isBoxed ? "M9 20h38M9 25h29" : "M5 20h46M5 25h34"}
        stroke="currentColor"
        strokeWidth="2"
        opacity="0.3"
      />
    </g>
  );
}

function TimelinePreview({
  value,
}: {
  value: ResumeTemplateLayout["timelineItemLayout"];
}) {
  return (
    <g>
      <rect
        x="5"
        y={value === "stacked" ? 6 : 8}
        width={
          value === "inline"
            ? 13
            : value === "stacked"
              ? 24
              : value === "compact"
                ? 25
                : 19
        }
        height="4"
        rx="1"
      />
      <path
        d={
          value === "inline"
            ? "M21 10h13M42 10h9M5 21h25"
            : value === "stacked"
              ? "M5 16h18M5 24h32"
              : value === "compact"
                ? "M5 21h19M39 10h12M43 21h8"
                : "M5 21h14M32 10h19M37 21h14"
        }
        stroke="currentColor"
        strokeWidth="2"
        opacity="0.4"
      />
    </g>
  );
}

function ListPreview({
  value,
}: {
  value: ResumeTemplateLayout["listItemLayout"];
}) {
  const positions =
    value === "columns"
      ? [
          [5, 10],
          [30, 10],
          [5, 22],
          [30, 22],
        ]
      : value === "inline"
        ? [
            [5, 16],
            [22, 16],
            [39, 16],
          ]
        : [
            [5, 8],
            [5, 16],
            [5, 24],
          ];
  const width = value === "list" ? 38 : value === "columns" ? 15 : 8;

  return positions.map(([x, y]) => (
    <g key={`${x}-${y}`}>
      <circle cx={x} cy={y} r="1.2" />
      <rect x={x + 4} y={y - 1} width={width} height="2" rx="1" opacity="0.4" />
    </g>
  ));
}

export function TemplateLayoutOptionPreview(
  props: TemplateLayoutOptionPreviewProps,
) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 56 32"
      fill="currentColor"
      className="text-muted-foreground"
      style={{ width: 56, height: 32 }}
    >
      <rect
        x="0.5"
        y="0.5"
        width="55"
        height="31"
        rx="4"
        fill="none"
        stroke="currentColor"
        opacity="0.18"
      />
      {props.kind === "basicInfo" ? (
        <BasicInfoPreview value={props.value} />
      ) : null}
      {props.kind === "section" ? <SectionPreview value={props.value} /> : null}
      {props.kind === "timeline" ? (
        <TimelinePreview value={props.value} />
      ) : null}
      {props.kind === "list" ? <ListPreview value={props.value} /> : null}
      {props.kind === "divider" ? (
        <line
          x1="6"
          y1="16"
          x2="50"
          y2="16"
          stroke="currentColor"
          strokeWidth={dividerStyleValues[props.value]}
        />
      ) : null}
    </svg>
  );
}
