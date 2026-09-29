import type { Editor } from "@tiptap/react";

export function syncEditorContent(editor: Editor, content: string) {
  const selection = editor.isFocused ? editor.state.selection : null;
  const commands = editor
    .chain()
    .setContent(content, { emitUpdate: false })
    .setMeta("addToHistory", false);
  if (selection) {
    commands.setTextSelection({
      from: selection.anchor,
      to: selection.head,
    });
  }
  commands.run();
}
