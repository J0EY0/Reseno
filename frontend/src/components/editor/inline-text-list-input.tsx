import { useState } from 'react'

import type { AppMessages } from '@/i18n'
import {
  formatRichTextAsPlainText,
  joinInlineText,
  serializeInlineTextFromHtml,
  serializeInlineTextToHtml,
} from '@/lib/rich-text'

import { InlineTextInput } from './inline-text-input'

function parseCommaSeparatedInlineText(value: string) {
  if (!formatRichTextAsPlainText(value)) {
    return value.split(/[,，]/).map((item) => item.trim()).filter(Boolean)
  }

  const document = new DOMParser().parseFromString(serializeInlineTextToHtml(value), 'text/html')
  const root = document.body.firstElementChild!
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const nodes: Array<{ node: Node; start: number; end: number }> = []
  let offset = 0
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const length = node.textContent?.length ?? 0
    nodes.push({ node, start: offset, end: offset + length })
    offset += length
  }

  const items: string[] = []
  for (const match of (root.textContent ?? '').matchAll(/[^,，]+/g)) {
    const text = match[0].trim()
    if (!text) continue
    const start = match.index + match[0].length - match[0].trimStart().length
    const end = start + text.length
    const first = nodes.find((node) => node.start <= start && node.end > start)!
    const last = nodes.find((node) => node.start < end && node.end >= end)!
    const range = document.createRange()
    range.setStart(first.node, start - first.start)
    range.setEnd(last.node, end - last.start)
    let fragment: Node = range.cloneContents()
    let ancestor = range.commonAncestorContainer
    if (ancestor.nodeType === Node.TEXT_NODE) ancestor = ancestor.parentNode!
    while (ancestor !== root) {
      const wrapper = ancestor.cloneNode(false)
      wrapper.appendChild(fragment)
      fragment = wrapper
      ancestor = ancestor.parentNode!
    }
    const container = document.createElement('p')
    container.appendChild(fragment)
    items.push(serializeInlineTextFromHtml(container.outerHTML))
  }
  return items
}

export function InlineTextListInput({
  t, value, onChange, ...props
}: {
  t: AppMessages
  value: string[]
  onChange: (value: string[]) => void
  'aria-label': string
  className?: string
  placeholder?: string
}) {
  const serializedValue = joinInlineText(value, ', ')
  const [inputState, setInputState] = useState(() => ({
    draft: serializedValue,
    publishedValue: serializedValue,
  }))
  const displayedValue = inputState.publishedValue === serializedValue
    ? inputState.draft
    : serializedValue

  return (
    <InlineTextInput
      {...props}
      t={t}
      value={displayedValue}
      onChange={(draft) => {
        const items = parseCommaSeparatedInlineText(draft)
        setInputState({ draft, publishedValue: joinInlineText(items, ', ') })
        onChange(items)
      }}
    />
  )
}
