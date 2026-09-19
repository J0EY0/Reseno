export const richHighlightsEditorContentClassName =
  "tiptap rich-text-editor rich-text-editor-scroll max-h-60 min-h-28 overflow-y-auto overscroll-contain cursor-text px-3 pt-2 pb-4 text-sm leading-[1.75] text-foreground outline-none [overflow-wrap:anywhere]";

export const richHighlightsEditorContainerClassName =
  "resume-editor-field overflow-hidden rounded-lg border border-border shadow-none";

export function getRichHighlightsEditorContent(html: string) {
  return /<\/(?:ul|ol)>\s*$/.test(html) ? `${html}<p></p>` : html || "<p></p>";
}
