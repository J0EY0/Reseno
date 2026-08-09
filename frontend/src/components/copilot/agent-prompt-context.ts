import languagePatterns from '@/lib/language-patterns.json'

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

const JOB_BRIEF_PROMPT_PATTERN = new RegExp(
  languagePatterns.jobBriefPrompt.map(escapeRegExp).join('|'),
  'i',
)
const JOB_BRIEF_CONTEXT_PATTERN = new RegExp(
  languagePatterns.jobBriefContext.map(escapeRegExp).join('|'),
  'i',
)

export function isLikelyJobBriefPrompt(prompt: string) {
  const trimmed = prompt.trim()
  const hasStructuredBody =
    trimmed.length >= 140 ||
    trimmed.split(/\n+/).filter(Boolean).length >= 3

  // Length alone cannot distinguish a JD from admission or scholarship rules.
  return (
    JOB_BRIEF_CONTEXT_PATTERN.test(trimmed) &&
    (hasStructuredBody || JOB_BRIEF_PROMPT_PATTERN.test(trimmed))
  )
}
