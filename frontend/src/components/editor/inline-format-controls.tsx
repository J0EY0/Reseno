import { useEditorState, type Editor } from "@tiptap/react";
import { Bold, Italic, Subscript, Superscript, Underline } from "lucide-react";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { AppMessages } from "@/i18n";

function AcademicItalicIcon() {
  return (
    <span
      aria-hidden="true"
      data-academic-italic="true"
      className="text-lg leading-none"
    >
      A
    </span>
  );
}

const marks = [
  { name: "bold", label: "richTextBold", icon: Bold },
  { name: "italic", label: "richTextItalic", icon: Italic },
  {
    name: "academicItalic",
    label: "richTextAcademicItalic",
    icon: AcademicItalicIcon,
  },
  { name: "underline", label: "richTextUnderline", icon: Underline },
  { name: "superscript", label: "richTextSuperscript", icon: Superscript },
  { name: "subscript", label: "richTextSubscript", icon: Subscript },
] as const;

export function InlineFormatControls({
  editor,
  t,
  visibleMarks,
}: {
  editor: Editor | null;
  t: AppMessages;
  visibleMarks?: readonly (typeof marks)[number]["name"][];
}) {
  const active =
    useEditorState({
      editor,
      selector: ({ editor: current }) =>
        marks
          .filter(({ name }) => current?.isActive(name))
          .map(({ name }) => name),
    }) ?? [];

  return (
    <ToggleGroup
      type="multiple"
      role="toolbar"
      aria-label={t.richTextFormatting}
      value={active}
      spacing={1}
      className="gap-0.5"
      onValueChange={(values) => {
        const mark = marks.find(
          ({ name }) => values.includes(name) !== active.includes(name),
        );
        if (mark) editor?.chain().focus().toggleMark(mark.name).run();
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          editor?.commands.focus();
        }
      }}
    >
      {marks
        .filter(({ name }) => !visibleMarks || visibleMarks.includes(name))
        .map(({ name, label, icon: Icon }) => (
          <ToggleGroupItem
            key={name}
            value={name}
            disabled={!editor}
            className="size-8 rounded-sm px-0"
            title={t[label]}
            aria-label={t[label]}
          >
            <Icon className="size-4" />
          </ToggleGroupItem>
        ))}
    </ToggleGroup>
  );
}
