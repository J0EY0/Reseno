export function stripRichText(html: string) {
  return html
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(div|p|li)>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/\u00a0/g, ' ')
    .replace(/\n{2,}/g, '\n')
    .trim()
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
