export const KIB = 1024

export const MAX_CHUNK_RAW_BYTES = 480_000
export const MAX_CHUNK_GZIP_BYTES = 140_000
export const DEFAULT_DYNAMIC_ENTRY_RAW_BYTES = 200 * KIB
export const DEFAULT_DYNAMIC_ENTRY_GZIP_BYTES = 65 * KIB
// The shell intentionally includes tw-animate-css so the shared shadcn/Radix
// dialogs, popovers, selects, and sheets retain their enter/exit transitions.
// Keep this ceiling close to that measured production baseline so future CSS
// growth still fails here instead of silently accumulating.
export const MAX_SHELL_CSS_RAW_BYTES = 162_000
export const MAX_SHELL_CSS_GZIP_BYTES = 26_600
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

export const dynamicEntryLegacyBudgets = new Map()

// These stable manifest roots describe the chunks fetched after each route is active.
export const routeBudgets = [
  {
    name: 'shell',
    roots: ['index.html'],
    maxGzipBytes: 136 * KIB,
  },
  {
    name: 'resume detail',
    roots: [
      'index.html',
      'src/components/workspace/workspace-preferences.tsx',
      'src/components/workspace/resume-detail-workspace-page.tsx',
      'src/components/preview/document-canvas.tsx',
    ],
    forbiddenStaticEntries: ['src/components/resume-builder.tsx'],
    maxGzipBytes: 248 * KIB,
  },
  {
    name: 'resume gallery',
    roots: [
      'index.html',
      'src/components/workspace/workspace-preferences.tsx',
      'src/components/workspace/workspace-lateral-layout.tsx',
      'src/components/workspace/resume-gallery-workspace-page.tsx',
    ],
    forbiddenStaticEntries: ['src/components/resume-builder.tsx'],
    maxGzipBytes: 224 * KIB,
  },
  {
    name: 'template gallery',
    roots: [
      'index.html',
      'src/components/workspace/workspace-preferences.tsx',
      'src/components/workspace/workspace-lateral-layout.tsx',
      'src/components/workspace/template-gallery-workspace-page.tsx',
    ],
    forbiddenStaticEntries: [
      'src/components/resume-builder.tsx',
      'src/components/templates/template-editor.tsx',
    ],
    maxGzipBytes: 224 * KIB,
  },
  {
    name: 'template detail',
    roots: [
      'index.html',
      'src/components/workspace/workspace-preferences.tsx',
      'src/components/workspace/template-detail-workspace-page.tsx',
      'src/components/preview/document-canvas.tsx',
    ],
    forbiddenStaticEntries: ['src/components/resume-builder.tsx'],
    // Keep both workspace and preview skeletons in the lazy route so loading
    // preserves the final surface hierarchy without a second visual jump.
    maxGzipBytes: 242 * KIB,
  },
  {
    name: 'trash',
    roots: [
      'index.html',
      'src/components/workspace/workspace-preferences.tsx',
      'src/components/workspace/workspace-lateral-layout.tsx',
      'src/components/workspace/trash-workspace-page.tsx',
    ],
    forbiddenStaticEntries: ['src/components/resume-builder.tsx'],
    maxGzipBytes: 243 * KIB,
  },
  {
    name: 'models',
    roots: [
      'index.html',
      'src/components/workspace/workspace-preferences.tsx',
      'src/components/workspace/workspace-lateral-layout.tsx',
      'src/components/workspace/models-workspace-page.tsx',
    ],
    forbiddenStaticEntries: ['src/components/resume-builder.tsx'],
    // The final dialog ships with the already-lazy route so first open never
    // swaps a nested lazy Spinner surface for the form.
    maxGzipBytes: 262 * KIB,
  },
  {
    name: 'settings',
    roots: [
      'index.html',
      'src/components/workspace/workspace-preferences.tsx',
      'src/components/workspace/workspace-lateral-layout.tsx',
      'src/components/workspace/settings-workspace-page.tsx',
    ],
    forbiddenStaticEntries: ['src/components/resume-builder.tsx'],
    maxGzipBytes: 233 * KIB,
  },
  {
    name: 'Agent',
    roots: [
      'index.html',
      'src/components/workspace/workspace-preferences.tsx',
      'src/components/workspace/resume-detail-workspace-page.tsx',
      'src/components/copilot/copilot-panel.tsx',
      'src/components/preview/document-canvas.tsx',
    ],
    forbiddenStaticEntries: ['src/components/resume-builder.tsx'],
    maxGzipBytes: 313 * KIB,
  },
]
