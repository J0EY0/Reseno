import Placeholder from "@tiptap/extension-placeholder";
import Underline from "@tiptap/extension-underline";
import {
  EditorContent,
  useEditor,
  useEditorState,
  type Editor,
} from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Ellipsis, List, ListOrdered, Redo2, Undo2 } from "lucide-react";
import { useEffect, useId, useState, type MouseEvent } from "react";

import { InlineFormatControls } from "./inline-format-controls";
import { resumeTextMarks } from "./resume-text-marks";
import {
  getRichHighlightsEditorContent,
  richHighlightsEditorContainerClassName,
  richHighlightsEditorContentClassName,
} from "./rich-highlights-editor-content";
import { RichHighlightsEditorSkeleton } from "./rich-highlights-editor-skeleton";

import type { AppMessages } from "@/i18n";
import {
  sanitizeRichTextHtml,
  serializeHighlightsToHtml,
} from "@/lib/rich-text";

import { Button } from "@/components/ui/button";

function preventToolbarBlur(event: MouseEvent<HTMLButtonElement>) {
  event.preventDefault();
}

function RichHighlightsToolbar({
  editor,
  t,
}: {
  editor: Editor | null;
  t: AppMessages;
}) {
  const [expanded, setExpanded] = useState(false);
  const extraControlsId = useId();
  const state = useEditorState({
    editor,
    selector: ({ editor: current }) => ({
      canUndo: current?.can().undo() ?? false,
      canRedo: current?.can().redo() ?? false,
      bulletList: current?.isActive("bulletList") ?? false,
      orderedList: current?.isActive("orderedList") ?? false,
    }),
  });

  return (
    <div className="flex flex-col gap-2 p-2 pb-0">
      <div className="flex flex-wrap items-center gap-0.5 text-muted-foreground">
        <InlineFormatControls
          editor={editor}
          t={t}
          visibleMarks={["bold", "italic"]}
        />
        <Button
          type="button"
          size="icon-sm"
          variant={state?.bulletList ? "secondary" : "ghost"}
          disabled={!editor}
          title={t.richTextBulletedList}
          aria-label={t.richTextBulletedList}
          aria-pressed={state?.bulletList ?? false}
          onMouseDown={preventToolbarBlur}
          onClick={() => editor?.chain().focus().toggleBulletList().run()}
        >
          <List />
        </Button>
        <Button
          type="button"
          size="icon-sm"
          variant={state?.orderedList ? "secondary" : "ghost"}
          disabled={!editor}
          title={t.richTextNumberedList}
          aria-label={t.richTextNumberedList}
          aria-pressed={state?.orderedList ?? false}
          onMouseDown={preventToolbarBlur}
          onClick={() => editor?.chain().focus().toggleOrderedList().run()}
        >
          <ListOrdered />
        </Button>
        <Button
          type="button"
          size="icon-sm"
          variant={expanded ? "secondary" : "ghost"}
          disabled={!editor}
          title={t.richTextMoreFormatting}
          aria-label={t.richTextMoreFormatting}
          aria-expanded={expanded}
          aria-controls={extraControlsId}
          onMouseDown={preventToolbarBlur}
          onClick={() => setExpanded((value) => !value)}
        >
          <Ellipsis />
        </Button>
      </div>
      <div id={extraControlsId} hidden={!expanded}>
        <div className="flex flex-wrap items-center gap-0.5 text-muted-foreground">
          <InlineFormatControls
            editor={editor}
            t={t}
            visibleMarks={[
              "academicItalic",
              "underline",
              "superscript",
              "subscript",
            ]}
          />
          <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            disabled={!state?.canUndo}
            title={t.richTextUndo}
            aria-label={t.richTextUndo}
            onMouseDown={preventToolbarBlur}
            onClick={() => editor?.chain().focus().undo().run()}
          >
            <Undo2 />
          </Button>
          <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            disabled={!state?.canRedo}
            title={t.richTextRedo}
            aria-label={t.richTextRedo}
            onMouseDown={preventToolbarBlur}
            onClick={() => editor?.chain().focus().redo().run()}
          >
            <Redo2 />
          </Button>
        </div>
      </div>
    </div>
  );
}

export function RichHighlightsEditor({
  t,
  label,
  value,
  placeholder,
  onChange,
}: {
  t: AppMessages;
  label: string;
  value: string[];
  placeholder: string;
  onChange: (value: string) => void;
}) {
  const labelId = useId();
  const editorValue = serializeHighlightsToHtml(value);

  const editor = useEditor(
    {
      immediatelyRender: false,
      extensions: [
        StarterKit.configure({
          heading: false,
          blockquote: false,
          code: false,
          codeBlock: false,
          horizontalRule: false,
          strike: false,
          underline: false,
          bulletList: {
            keepMarks: true,
            keepAttributes: false,
          },
          orderedList: {
            keepMarks: true,
            keepAttributes: false,
          },
        }),
        Underline,
        ...resumeTextMarks,
        Placeholder.configure({
          placeholder,
          emptyEditorClass: "is-editor-empty",
        }),
      ],
      content: getRichHighlightsEditorContent(editorValue),
      editorProps: {
        attributes: {
          class: richHighlightsEditorContentClassName,
          role: "textbox",
          "aria-multiline": "true",
          "aria-labelledby": labelId,
        },
      },
      onUpdate({ editor: currentEditor }) {
        onChange(sanitizeRichTextHtml(currentEditor.getHTML()));
      },
    },
    [placeholder],
  );

  useEffect(() => {
    if (!editor) {
      return;
    }

    const currentValue = sanitizeRichTextHtml(editor.getHTML());

    if (currentValue === editorValue) {
      return;
    }

    editor.commands.setContent(getRichHighlightsEditorContent(editorValue), {
      emitUpdate: false,
    });
  }, [editor, editorValue]);

  if (!editor) {
    return <RichHighlightsEditorSkeleton label={label} value={value} />;
  }

  return (
    <div className="group/rich-editor flex min-w-0 flex-col gap-2">
      <span
        id={labelId}
        className="text-xs font-medium leading-tight text-muted-foreground transition-colors group-focus-within/rich-editor:text-foreground"
      >
        {label}
      </span>
      <div className={richHighlightsEditorContainerClassName}>
        <RichHighlightsToolbar editor={editor} t={t} />
        <div onClick={() => editor.chain().focus().run()}>
          <EditorContent editor={editor} />
        </div>
      </div>
    </div>
  );
}
