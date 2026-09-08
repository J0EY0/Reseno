import type { AppMessages } from '@/i18n'
import { createId } from '@/lib/resume-id'
import { createResumeSection } from '@/lib/resume-sections'
import { getRichTextPlainText } from '@/lib/rich-text'
import type { ResumeData, SectionKind } from '@/types/resume'

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

export function getSectionTitle(
  section: { kind: SectionKind; title: string },
  t: AppMessages,
) {
  return section.title.trim() || t.sectionTitles[section.kind]
}

export function getInitials(name: string) {
  const tokens = getRichTextPlainText(name).trim().split(/\s+/).filter(Boolean)

  if (tokens.length === 0) {
    return 'RM'
  }

  return tokens
    .slice(0, 2)
    .map((token) => token[0]?.toUpperCase() ?? '')
    .join('')
}
