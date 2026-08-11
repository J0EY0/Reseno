export function stripRichText(html: string) {
  return html
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(div|p|li)>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/\u00a0/g, ' ')
    .replace(/\n{2,}/g, '\n')
    .trim()
}

const CANONICAL_RICH_TEXT_ENTITIES: Record<string, string> = {
  amp: '&',
  lt: '<',
  gt: '>',
  quot: '"',
  '#39': "'",
  nbsp: ' ',
}

function decodeCanonicalRichTextEntities(value: string) {
  // Decode once so text that intentionally contains "&lt;" is not decoded twice.
  return value.replace(
    /&(amp|lt|gt|quot|nbsp|#(?:x[0-9a-f]+|\d+));/gi,
    (entity, name: string) => {
      const normalized = name.toLowerCase()
      const named = CANONICAL_RICH_TEXT_ENTITIES[normalized]
      if (named !== undefined) {
        return named
      }

      const numeric = normalized.startsWith('#x')
        ? Number.parseInt(normalized.slice(2), 16)
        : Number.parseInt(normalized.slice(1), 10)
      if (
        !Number.isInteger(numeric) ||
        numeric <= 0 ||
        numeric > 0x10ffff ||
        (numeric >= 0xd800 && numeric <= 0xdfff)
      ) {
        return entity
      }
      return numeric === 0xa0 ? ' ' : String.fromCodePoint(numeric)
    },
  )
}

const CANONICAL_RICH_TEXT_TAGS = new Set([
  'b',
  'br',
  'div',
  'em',
  'i',
  'li',
  'ol',
  'p',
  'strong',
  'u',
  'ul',
])

/**
 * Convert a canonical resume rich-text document into a compact text
 * representation for read-only surfaces such as change summaries.
 *
 * Detection is based on the stored markup rather than a resume field name.
 * Strings without a complete canonical tag remain untouched, so ordinary text
 * containing angle brackets is not mistaken for rich text.
 */
export function formatRichTextAsPlainText(value: string) {
  const root = value.match(/^\s*<(div|ol|p|ul)(?:\s|>)/i)
  if (!root) {
    return null
  }
  const rootTag = root[1].toLowerCase()
  if (!new RegExp(`</${rootTag}\\s*>`, 'i').test(value)) {
    return null
  }
  const blockKind = rootTag === 'ol' || rootTag === 'ul' ? 'list' : 'flow'

  const tagPattern = /<!--[\s\S]*?-->|<\/?([a-z][a-z0-9-]*)\b[^<>]*>/gi
  const lines: string[] = []
  const listStack: Array<{ index: number; ordered: boolean }> = []
  let currentLine = ''
  let currentLineHasText = false
  let cursor = 0

  const appendText = (rawText: string) => {
    const text = decodeCanonicalRichTextEntities(rawText).replace(/\s+/g, ' ')
    if (!text) {
      return
    }
    if (!text.trim()) {
      if (currentLine && !currentLine.endsWith(' ')) {
        currentLine += ' '
      }
      return
    }
    currentLine += currentLine ? text : text.trimStart()
    currentLineHasText = true
  }

  const finishLine = () => {
    const line = currentLine.trimEnd()
    if (line.trim()) {
      lines.push(line)
    }
    currentLine = ''
    currentLineHasText = false
  }

  for (const match of value.matchAll(tagPattern)) {
    appendText(value.slice(cursor, match.index))
    cursor = (match.index ?? 0) + match[0].length

    if (!match[1]) {
      continue
    }

    const tagName = match[1].toLowerCase()
    if (!CANONICAL_RICH_TEXT_TAGS.has(tagName)) {
      continue
    }

    const closing = match[0].startsWith('</')

    if (tagName === 'br') {
      finishLine()
      continue
    }

    if (tagName === 'ul' || tagName === 'ol') {
      if (closing) {
        finishLine()
        listStack.pop()
      } else {
        finishLine()
        listStack.push({ index: 0, ordered: tagName === 'ol' })
      }
      continue
    }

    if (tagName === 'li') {
      if (closing) {
        finishLine()
      } else {
        finishLine()
        const list = listStack.at(-1)
        const index = list?.index ?? 0
        const prefix = list?.ordered ? `${index + 1}. ` : '• '
        currentLine = `${'  '.repeat(Math.max(0, listStack.length - 1))}${prefix}`
        if (list) {
          list.index += 1
        }
      }
      continue
    }

    if (tagName === 'p' || tagName === 'div') {
      if (closing || currentLineHasText) {
        finishLine()
      }
    }
  }

  appendText(value.slice(cursor))
  finishLine()
  return {
    blockKind,
    text: lines.join('\n').trim(),
  }
}

function escapeHtml(value: string) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function normalizeTagName(tagName: string) {
  const normalized = tagName.toLowerCase()

  if (normalized === 'b') {
    return 'strong'
  }

  if (normalized === 'i') {
    return 'em'
  }

  return normalized
}

function sanitizeNode(node: ChildNode): string {
  if (node.nodeType === Node.TEXT_NODE) {
    return escapeHtml(node.textContent ?? '')
  }

  if (node.nodeType !== Node.ELEMENT_NODE) {
    return ''
  }

  const element = node as HTMLElement
  const tagName = normalizeTagName(element.tagName)
  const children = Array.from(element.childNodes)
    .map((child) => sanitizeNode(child))
    .join('')

  switch (tagName) {
    case 'strong':
    case 'em':
    case 'u':
      return `<${tagName}>${children}</${tagName}>`
    case 'ul':
    case 'ol':
      return stripRichText(children).length > 0
        ? `<${tagName}>${children}</${tagName}>`
        : ''
    case 'li':
      return stripRichText(children).length > 0
        ? `<li>${children}</li>`
        : ''
    case 'br':
      return '<br>'
    case 'div':
    case 'p':
      return stripRichText(children).length > 0
        ? `<p>${children}</p>`
        : ''
    default:
      return children
  }
}

export function sanitizeRichTextHtml(value: string) {
  if (!value.trim()) {
    return ''
  }

  if (typeof window === 'undefined') {
    return escapeHtml(stripRichText(value))
  }

  const parser = new window.DOMParser()
  const document = parser.parseFromString(value, 'text/html')
  const sanitized = Array.from(document.body.childNodes)
    .map((node) => sanitizeNode(node))
    .join('')
    .replace(/(<p>\s*<\/p>)+/g, '')
    .replace(/(<br>\s*){3,}/g, '<br><br>')
    .replace(/^(<br>\s*)+|(<br>\s*)+$/g, '')

  return sanitized
}

export function isRichTextEmpty(value: string) {
  return stripRichText(value).length === 0
}

export function serializeHighlightsToHtml(highlights: string[]) {
  const visibleHighlights = highlights.filter((item) => !isRichTextEmpty(item))

  if (visibleHighlights.length === 0) {
    return ''
  }

  if (visibleHighlights.length === 1) {
    return sanitizeRichTextHtml(visibleHighlights[0])
  }

  return `<ul>${visibleHighlights
    .map((item) => `<li>${sanitizeRichTextHtml(item)}</li>`)
    .join('')}</ul>`
}

export function serializeListItemsToHtml(items: string[]) {
  const visibleItems = items.filter((item) => !isRichTextEmpty(item))

  if (visibleItems.length === 0) {
    return ''
  }

  return `<ul>${visibleItems
    .map((item) => `<li>${sanitizeRichTextHtml(item)}</li>`)
    .join('')}</ul>`
}
