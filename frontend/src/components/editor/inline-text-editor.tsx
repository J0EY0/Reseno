import Document from '@tiptap/extension-document'
import Placeholder from '@tiptap/extension-placeholder'
import { EditorContent, useEditor } from '@tiptap/react'
import { BubbleMenu } from '@tiptap/react/menus'
import StarterKit from '@tiptap/starter-kit'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import {
  serializeInlineTextFromHtml,
  serializeInlineTextToHtml,
} from '@/lib/rich-text'
import { cn } from '@/lib/utils'

import { InlineFormatControls } from './inline-format-controls'
import type { InlineTextInputProps } from './inline-text-input'
import { resumeTextMarks } from './resume-text-marks'

const InlineDocument = Document.extend({ content: 'paragraph' })
const menuOptions = {
  strategy: 'fixed',
  placement: 'top',
  offset: 8,
  flip: true,
  shift: { padding: 8 },
} as const

export default function InlineTextEditor({
  id,
  'aria-label': label,
  className,
  multiline = false,
  placeholder,
  t,
  value,
  onChange,
}: InlineTextInputProps) {
  const menuRef = useRef<HTMLDivElement>(null)
  const [menuHost, setMenuHost] = useState<HTMLDivElement | null>(null)
  const editorValue = serializeInlineTextToHtml(value, multiline)
  const editorClassName = cn(
    'tiptap rich-text-editor w-full min-w-0 rounded-md border border-input bg-transparent px-3 py-1 text-base text-foreground shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 md:text-sm dark:bg-input/30',
    multiline
      ? 'min-h-16 whitespace-pre-wrap break-words py-2'
      : 'rich-text-editor-scroll flex h-9 items-center overflow-x-auto whitespace-pre [&>p]:min-w-full [&>p]:shrink-0',
    className,
  )

  const editor = useEditor({
    immediatelyRender: false,
    shouldRerenderOnTransaction: false,
    extensions: [
      StarterKit.configure({
        document: false,
        heading: false,
        blockquote: false,
        bulletList: false,
        orderedList: false,
        listItem: false,
        listKeymap: false,
        code: false,
        codeBlock: false,
        horizontalRule: false,
        strike: false,
        link: false,
        dropcursor: false,
        gapcursor: false,
        trailingNode: false,
      }),
      InlineDocument,
      ...resumeTextMarks,
      Placeholder.configure({ placeholder: placeholder ?? '', emptyEditorClass: 'is-editor-empty' }),
    ],
    content: editorValue,
    editorProps: {
      attributes: {
        id: id ?? '',
        role: 'textbox',
        'aria-label': label,
        'aria-multiline': String(multiline),
        'aria-keyshortcuts': 'Alt+F10',
        class: editorClassName,
      },
      transformPastedHTML: (html) => serializeInlineTextToHtml(
        serializeInlineTextFromHtml(html, multiline), multiline,
      ),
      transformPastedText: (text) => multiline ? text : text.replace(/\r\n?|\n/g, ' '),
      handleKeyDown: (_view, event) => {
        if (event.altKey && event.key === 'F10') {
          const button = menuRef.current?.querySelector<HTMLButtonElement>('button')
          if (button && menuRef.current?.style.visibility !== 'hidden') {
            button.focus()
            return true
          }
        }
        if (event.key === 'Enter' && !event.isComposing) {
          if (multiline) editor?.commands.setHardBreak()
          return true
        }
        return false
      },
    },
    onUpdate({ editor: current }) {
      onChange(serializeInlineTextFromHtml(current.getHTML(), multiline))
    },
  }, [multiline, placeholder])

  useEffect(() => {
    if (!editor || serializeInlineTextToHtml(
      serializeInlineTextFromHtml(editor.getHTML(), multiline), multiline,
    ) === editorValue) return
    editor.commands.setContent(editorValue, { emitUpdate: false })
  }, [editor, editorValue, multiline])

  return (
    <>
      <EditorContent editor={editor} className="min-w-0" />
      {createPortal(<div ref={setMenuHost} className="contents" />, document.body)}
      {editor && menuHost ? (
        <BubbleMenu
          editor={editor}
          ref={menuRef}
          appendTo={menuHost}
          options={menuOptions}
          updateDelay={0}
          className="z-50 rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-md"
        >
          <InlineFormatControls editor={editor} t={t} />
        </BubbleMenu>
      ) : !editor ? <div className={editorClassName} aria-hidden="true">&nbsp;</div> : null}
    </>
  )
}
