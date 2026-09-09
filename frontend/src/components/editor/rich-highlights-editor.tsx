import Placeholder from "@tiptap/extension-placeholder";
import Underline from "@tiptap/extension-underline";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { List, ListOrdered, Redo2, Undo2 } from "lucide-react";
import { useEffect, type MouseEvent } from "react";

import { InlineFormatControls } from "./inline-format-controls";
import { resumeTextMarks } from "./resume-text-marks";

import type { AppMessages } from "@/i18n";
import {
  sanitizeRichTextHtml,
  serializeHighlightsToHtml,
} from "@/lib/rich-text";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

const richHighlightsEditorContentClassName =
  "tiptap rich-text-editor rich-text-editor-scroll max-h-[160px] min-h-[120px] overflow-y-auto overscroll-contain cursor-text text-sm leading-[1.12] text-foreground outline-none";

function preventToolbarBlur(event: MouseEvent<HTMLButtonElement>) {
  event.preventDefault();
}

export function RichHighlightsEditor({
  t,
  value,
  onChange,
}: {
  t: AppMessages;
  value: string[];
  onChange: (value: string) => void;
}) {
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
          placeholder: t.placeholders.highlightItem,
          emptyEditorClass: "is-editor-empty",
        }),
      ],
      content: editorValue || "<p></p>",
      editorProps: {
        attributes: {
          class: richHighlightsEditorContentClassName,
        },
      },
      onUpdate({ editor: currentEditor }) {
        onChange(sanitizeRichTextHtml(currentEditor.getHTML()));
      },
    },
    [t.placeholders.highlightItem],
  );

  useEffect(() => {
    if (!editor) {
      return;
    }

    const currentValue = sanitizeRichTextHtml(editor.getHTML());

    if (currentValue === editorValue) {
      return;
    }

    editor.commands.setContent(editorValue || "<p></p>", {
      emitUpdate: false,
    });
  }, [editor, editorValue]);

  function runCommand(action: () => boolean) {
    action();
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border/70 bg-muted/30 transition-colors focus-within:border-ring/50 focus-within:ring-1 focus-within:ring-ring/20">
      <div className="flex flex-wrap items-center gap-0.5 border-b border-border/60 bg-muted/25 px-2 py-1">
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="size-8"
          disabled={!editor?.can().undo()}
          title={t.richTextUndo}
          aria-label={t.richTextUndo}
          onMouseDown={preventToolbarBlur}
          onClick={() =>
            runCommand(() => editor?.chain().focus().undo().run() ?? false)
          }
        >
          <Undo2 className="size-4" />
        </Button>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="size-8"
          disabled={!editor?.can().redo()}
          title={t.richTextRedo}
          aria-label={t.richTextRedo}
          onMouseDown={preventToolbarBlur}
          onClick={() =>
            runCommand(() => editor?.chain().focus().redo().run() ?? false)
          }
        >
          <Redo2 className="size-4" />
        </Button>
        <InlineFormatControls editor={editor} t={t} />
        <Button
          type="button"
          size="icon"
          variant={editor?.isActive("bulletList") ? "secondary" : "ghost"}
          className="size-8"
          title={t.richTextBulletedList}
          aria-label={t.richTextBulletedList}
          onMouseDown={preventToolbarBlur}
          onClick={() =>
            runCommand(
              () => editor?.chain().focus().toggleBulletList().run() ?? false,
            )
          }
        >
          <List className="size-4" />
        </Button>
        <Button
          type="button"
          size="icon"
          variant={editor?.isActive("orderedList") ? "secondary" : "ghost"}
          className="size-8"
          title={t.richTextNumberedList}
          aria-label={t.richTextNumberedList}
          onMouseDown={preventToolbarBlur}
          onClick={() =>
            runCommand(
              () => editor?.chain().focus().toggleOrderedList().run() ?? false,
            )
          }
        >
          <ListOrdered className="size-4" />
        </Button>
      </div>

      {editor ? (
        <div
          className="min-h-[140px] bg-background/65 px-3 py-2.5"
          onClick={() => editor.chain().focus().run()}
        >
          <EditorContent editor={editor} />
        </div>
      ) : (
        <div className="min-h-[140px] bg-background/65 px-3 py-2.5">
          <Skeleton>
            <div
              aria-hidden="true"
              className={`${richHighlightsEditorContentClassName} invisible`}
              dangerouslySetInnerHTML={{
                __html: editorValue || "<p></p>",
              }}
            />
          </Skeleton>
        </div>
      )}
    </div>
  );
}
