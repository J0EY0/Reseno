export const KIB = 1024

export const MAX_CHUNK_RAW_BYTES = 480_000
export const MAX_CHUNK_GZIP_BYTES = 140_000
export const DEFAULT_DYNAMIC_ENTRY_RAW_BYTES = 200 * KIB
export const DEFAULT_DYNAMIC_ENTRY_GZIP_BYTES = 65 * KIB
export const MAX_SHELL_CSS_RAW_BYTES = 155_000
export const MAX_SHELL_CSS_GZIP_BYTES = 25_500
export const RATCHET_THRESHOLD = 0.95

export const conditionalFontCssBudgets = [
  {
    name: 'Noto Sans SC',
    manifestKeySuffix: '/@fontsource-variable/noto-sans-sc/wght.css',
    maxRawBytes: 110_000,
    maxGzipBytes: 45_000,
  },
  {
    name: 'Noto Serif SC',
    manifestKeySuffix: '/@fontsource-variable/noto-serif-sc/wght.css',
    maxRawBytes: 110_000,
    maxGzipBytes: 45_000,
  },
]

export const dynamicEntryLegacyBudgets = new Map([
  [
    'src/components/editor/rich-highlights-editor.tsx',
    { maxRawBytes: 376_000, maxGzipBytes: 116_500 },
  ],
])

// These stable manifest roots describe the chunks fetched after each route is active.
export const routeBudgets = [
  {
    name: 'shell',
    roots: ['index.html'],
    maxGzipBytes: 127 * KIB,
  },
  {
    name: 'resume detail',
    roots: [
      'index.html',
      'src/components/workspace/resume-detail-workspace-page.tsx',
      'src/components/preview/document-preview-card.tsx',
    ],
    forbiddenStaticEntries: ['src/components/resume-builder.tsx'],
    maxGzipBytes: 242 * KIB,
  },
  {
    name: 'resume gallery',
    roots: [
      'index.html',
      'src/components/workspace/resume-gallery-workspace-page.tsx',
    ],
    forbiddenStaticEntries: ['src/components/resume-builder.tsx'],
    maxGzipBytes: 205 * KIB,
  },
  {
    name: 'template gallery',
    roots: [
      'index.html',
      'src/components/workspace/template-gallery-workspace-page.tsx',
    ],
    forbiddenStaticEntries: [
      'src/components/resume-builder.tsx',
      'src/components/templates/template-editor.tsx',
    ],
    maxGzipBytes: 205 * KIB,
  },
  {
    name: 'template detail',
    roots: [
      'index.html',
      'src/components/workspace/template-detail-workspace-page.tsx',
      'src/components/preview/document-preview-card.tsx',
    ],
    forbiddenStaticEntries: ['src/components/resume-builder.tsx'],
    maxGzipBytes: 220 * KIB,
  },
  {
    name: 'trash',
    roots: [
      'index.html',
      'src/components/workspace/trash-workspace-page.tsx',
    ],
    forbiddenStaticEntries: ['src/components/resume-builder.tsx'],
    maxGzipBytes: 205 * KIB,
  },
  {
    name: 'models',
    roots: [
      'index.html',
      'src/components/workspace/models-workspace-page.tsx',
    ],
    forbiddenStaticEntries: ['src/components/resume-builder.tsx'],
    maxGzipBytes: 230 * KIB,
  },
  {
    name: 'settings',
    roots: [
      'index.html',
      'src/components/workspace/settings-workspace-page.tsx',
    ],
    forbiddenStaticEntries: ['src/components/resume-builder.tsx'],
    maxGzipBytes: 224 * KIB,
  },
  {
    name: 'Agent',
    roots: [
      'index.html',
      'src/components/workspace/resume-detail-workspace-page.tsx',
      'src/components/copilot/copilot-panel.tsx',
      'src/components/preview/document-preview-card.tsx',
    ],
    forbiddenStaticEntries: ['src/components/resume-builder.tsx'],
    maxGzipBytes: 310 * KIB,
  },
]
