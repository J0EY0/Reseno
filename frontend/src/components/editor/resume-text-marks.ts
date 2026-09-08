import Subscript from '@tiptap/extension-subscript'
import Superscript from '@tiptap/extension-superscript'
import { Mark } from '@tiptap/react'

const AcademicItalic = Mark.create({
  name: 'academicItalic',
  parseHTML() {
    return [{ tag: 'span[data-academic-italic="true"]' }]
  },
  renderHTML() {
    return ['span', { 'data-academic-italic': 'true' }, 0]
  },
})

export const resumeTextMarks = [
  AcademicItalic,
  Superscript.extend({ excludes: 'subscript' }),
  Subscript.extend({ excludes: 'superscript' }),
]
