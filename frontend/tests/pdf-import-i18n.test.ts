import assert from "node:assert/strict";
import { it } from "vitest";
import { detectPdfResumeDocumentLocale } from "@/lib/pdf-resume-import/document-language";
import {
  createResumeImportLexiconContext,
  extractPeriod,
} from "@/lib/pdf-resume-import/parser-config";
import {
  buildResumeFromLines,
  line,
  requiredSection,
  resumeImportLexicon,
} from "./helpers/pdf-import-fixtures";

it("recognizes English month dates and both numeric date orders", () => {
  const context = createResumeImportLexiconContext(resumeImportLexicon);
  for (const period of [
    "Jan 2020 – Present",
    "September 2020 - Feb. 2023",
    "2020 Jan - 2023 February",
    "Jan. 2020 to December 2023",
    "01/2020 - 12/2023",
    "01.2020 – 12.2023",
    "2020年01月 至 现在",
    "2020.01 - 至今",
    "2024-09 ~ 2027-06",
    "2024.09 ~ 至今",
  ]) {
    assert.equal(extractPeriod([period], context), period);
  }
  for (const invalid of [
    "Jan 2020 - NotAMonth 2023",
    "Jan 2020 - Feb 2023extra",
    "13/2020 - 12/2023",
    "2020 - 2023.99",
    "Jan 2200 - Feb 2201",
  ]) {
    assert.equal(extractPeriod([invalid], context), "", invalid);
  }
});

it("uses month words from every backend locale without English parser vocabulary", () => {
  const context = createResumeImportLexiconContext({
    locales: {
      synthetic: {
        documentTitleTerms: ["Career"],
        currentPeriodTerms: ["ongoing+"],
        dateRangeTerms: ["through+"],
        datePartSeparators: [],
        datePartSuffixes: [],
        monthNames: ["Month+"],
      },
    },
  });
  assert.equal(
    extractPeriod(["Month+ 2020 through+ ongoing+"], context),
    "Month+ 2020 through+ ongoing+",
  );
  assert.equal(extractPeriod(["Jan 2020 - Feb 2023"], context), "");
});

it("keeps a named-month period out of the imported company and job title", () => {
  const resume = buildResumeFromLines(
    [
      line("王小明", 0),
      line("user@example.com", 1),
      line("Work Experience", 2, 14),
      line("Example Organization", 3),
      line("Jan 2020 – Present", 4),
      line("Software Engineer", 5),
      line("• Built reliable infrastructure for customers.", 6),
    ],
    "Imported content",
  );
  const item = requiredSection(resume, "experience").items[0];
  assert.equal(item?.period, "Jan 2020 – Present");
  assert.equal(item?.company, "Example Organization");
  assert.equal(item?.position, "Software Engineer");
});

it("chooses the document locale from body language despite mixed names and contacts", () => {
  assert.equal(
    detectPdfResumeDocumentLocale([
      line("王小明", 0),
      line("xiaoming@example.com https://example.com/experience", 1),
      line("Software Engineer", 2),
      line("Professional Experience", 3),
      line("Built reliable infrastructure and led a team of engineers.", 4),
      line("Education", 5),
      line("Master of Computer Science", 6),
    ]),
    "en",
  );
  assert.equal(
    detectPdfResumeDocumentLocale([
      line("Xiaoming Wang", 0),
      line("xiaoming@example.com https://example.com/experience", 1),
      line("技术能力", 2),
      line("熟悉 React、TypeScript、Node.js、Docker、PostgreSQL。", 3),
      line("工作经历", 4),
      line("负责平台开发及服务性能优化，推动团队交付。", 5),
      line("教育背景", 6),
      line("计算机科学硕士", 7),
    ]),
    "zh",
  );
  assert.equal(
    detectPdfResumeDocumentLocale([
      line("陳小明", 0),
      line("專業技能", 1),
      line("負責網站開發及團隊協作，熟悉 React 與 TypeScript。", 2),
    ]),
    "zh",
  );
  assert.equal(
    detectPdfResumeDocumentLocale([
      line("Иван Петров", 0),
      line("Опыт работы", 1),
      line("Разработчик программного обеспечения", 2),
    ]),
    "en",
  );
  assert.equal(
    detectPdfResumeDocumentLocale([
      line("田中太郎", 0),
      line("職務経歴", 1),
      line("ソフトウェアエンジニアとしてシステムの開発を担当しています。", 2),
    ]),
    "en",
  );
});
