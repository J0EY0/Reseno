import type { AppMessages } from '@/i18n'
import languagePatterns from '@/lib/language-patterns.json'
import { createId } from '@/lib/resume-id'
import {
  createResumeSection,
  projectResumeSections,
} from '@/lib/resume-sections'
import { stripRichText } from '@/lib/rich-text'
import type {
  KeywordMatch,
  ResumeData,
  SectionKind,
} from '@/types/resume'

const latinStopWords = new Set(languagePatterns.keywordStopWords.latin)
const cjkStopWords = new Set(languagePatterns.keywordStopWords.cjk)

export { createId, createResumeSection as createSection }

export function createEmptyResume(): ResumeData {
  return {
    schemaVersion: 2,
    basic: {
      name: '',
      headline: '',
      phone: '',
      email: '',
      location: '',
      avatar: '',
      summary: '',
      customFields: [],
    },
    sections: [
      createResumeSection('education'),
      createResumeSection('experience'),
      createResumeSection('project'),
    ],
  }
}

export function createCollapsedState(resume: ResumeData) {
  return resume.sections.reduce(
    (state, section) => {
      state[section.id] = false
      return state
    },
    { basic: false } as Record<string, boolean>,
  )
}

export function getSectionTitle(
  section: { kind: SectionKind; title: string },
  t: AppMessages,
) {
  return section.title.trim() || t.sectionTitles[section.kind]
}

export function getSectionSummary(
  section: { items: readonly unknown[] },
  t: AppMessages,
) {
  const itemLabel = section.items.length === 1 ? t.itemCountSingular : t.itemCount

  return `${section.items.length} ${itemLabel}`
}

export function getInitials(name: string) {
  const tokens = name.trim().split(/\s+/).filter(Boolean)

  if (tokens.length === 0) {
    return 'RM'
  }

  return tokens
    .slice(0, 2)
    .map((token) => token[0]?.toUpperCase() ?? '')
    .join('')
}

function extractKeywords(text: string) {
  const normalizedLatin = text
    .toLowerCase()
    .split(/[\s,.;:()/-]+/)
    .map((token) => token.replace(/[^a-z0-9+#]/g, ''))
    .filter((token) => token.length > 2 && !latinStopWords.has(token))

  const chineseMatches =
    text
      .match(/[\u4e00-\u9fff]{2,8}/g)
      ?.filter((token) => !cjkStopWords.has(token)) ?? []

  return Array.from(new Set([...normalizedLatin, ...chineseMatches]))
}

function buildResumeText(resume: ResumeData) {
  const sections = projectResumeSections(resume.sections)

  return [
    resume.basic.name,
    resume.basic.headline,
    resume.basic.phone,
    resume.basic.email,
    resume.basic.location,
    resume.basic.summary,
    ...resume.basic.customFields.flatMap((field) => [field.label, field.value]),
    ...sections.flatMap((section) => [
      section.title,
      ...section.items.flatMap((item) => [
        item.title,
        item.subtitle,
        item.meta,
        item.period,
        item.url,
        stripRichText(item.content),
        item.description,
        ...item.highlights.map((value) => stripRichText(value)),
      ]),
    ]),
  ].join(' ')
}

export function getKeywordMatch(
  resume: ResumeData,
  jobBrief: string,
  appliedCount: number,
  t: AppMessages,
): KeywordMatch {
  const resumeKeywords = new Set(extractKeywords(buildResumeText(resume)))
  const prioritized = extractKeywords(jobBrief).slice(0, 12)
  const matched = prioritized.filter((keyword) => resumeKeywords.has(keyword))
  const missing = prioritized.filter((keyword) => !resumeKeywords.has(keyword))
  const structureSignals = [
    resume.basic.name,
    resume.basic.phone,
    resume.basic.email,
    resume.sections.some((section) => section.kind === 'education') ? 'education' : '',
    resume.sections.some((section) => section.kind === 'experience')
      ? 'experience'
      : '',
    resume.sections.some((section) => section.kind === 'project') ? 'project' : '',
    resume.sections.some((section) => section.kind === 'achievement')
      ? 'achievement'
      : '',
    resume.sections.some((section) => section.kind === 'simple_list')
      ? 'simple-list'
      : '',
  ].filter(Boolean).length

  const structureScore = Math.min(42, structureSignals * 6)
  const keywordScore = prioritized.length
    ? Math.round((matched.length / prioritized.length) * 42)
    : 18
  const enhancementScore = Math.min(16, appliedCount * 5)
  const score = Math.min(98, structureScore + keywordScore + enhancementScore)
  const summary =
    score >= 76
      ? t.scoreSummaryGood
      : t.scoreSummaryWeak

  return { score, matched, missing, summary }
}
