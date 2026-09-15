import assert from "node:assert/strict";
import { File as NodeFile } from "node:buffer";
import registryJson from "../../../backend/app/services/agent/section_registry.json";
import lexiconJson from "../../../backend/app/services/resume_import_lexicon.json";
import zhFixture from "../../scripts/fixtures/pdf-import/zh-minimal-structure.json";
import type {
  ResumeData,
  ResumeSectionItem,
  SectionKind,
  ResumeSectionOf,
} from "@/types/resume";
import { buildResumeFromPdfLines } from "@/lib/pdf-resume-import/parser";
import type {
  ResumeImportLexiconResponse,
  SectionRegistryResponse,
} from "@/lib/pdf-resume-import/parser-config";
import type {
  TextLine,
  textContentToLinesForResumeImport,
} from "@/lib/pdf-resume-import/pdf-text-extraction";

export const sectionRegistry: SectionRegistryResponse =
  registryJson as SectionRegistryResponse;
export const resumeImportLexicon: ResumeImportLexiconResponse = lexiconJson;
export const zhMinimalStructureFixture: Parameters<
  typeof textContentToLinesForResumeImport
>[0] & { page: number } = zhFixture;

export function buildResumeFromLines(
  lines: TextLine[],
  fallbackSectionTitle: string,
  lexicon = resumeImportLexicon,
) {
  return buildResumeFromPdfLines(
    lines,
    fallbackSectionTitle,
    sectionRegistry,
    lexicon,
  ).resume;
}

export function requiredLine(lines: TextLine[], text: string) {
  const matched = lines.find((line) => line.text === text);
  assert.ok(matched, `Expected extracted line: ${text}`);
  return matched;
}

type KindAliases = {
  work: "experience";
  internship: "experience";
  skills: "simple_list";
  languages: "simple_list";
  other: "simple_list";
  awards: "achievement";
};

export function requiredSection<K extends SectionKind | keyof KindAliases>(
  resume: ResumeData,
  kind: K,
): ResumeSectionOf<
  K extends keyof KindAliases ? KindAliases[K] : K & SectionKind
> {
  const semanticKind =
    (
      {
        work: "experience",
        internship: "experience",
        skills: "simple_list",
        languages: "simple_list",
        other: "simple_list",
        awards: "achievement",
      } as Record<string, SectionKind>
    )[kind] ?? kind;
  const titleMatcher = (
    {
      internship: /intern|实习/i,
      skills: /skill|技能|技术栈/i,
      languages: /language|语言/i,
      other: /other|其他|自定义/i,
    } as Record<string, RegExp>
  )[kind];
  const candidates = resume.sections.filter(
    (candidate) => candidate.kind === semanticKind,
  );
  const section =
    candidates.find(
      (candidate) => !titleMatcher || titleMatcher.test(candidate.title),
    ) ??
    (kind === "internship" && candidates.length === 1
      ? candidates[0]
      : undefined);
  assert.ok(section, `Expected imported section kind: ${kind}`);
  return section as ResumeSectionOf<
    K extends keyof KindAliases ? KindAliases[K] : K & SectionKind
  >;
}

export function selectItemFields(item: ResumeSectionItem) {
  if ("school" in item) {
    return {
      title: item.school,
      subtitle: [item.degree, item.major].filter(Boolean).join(" · "),
      meta: [item.gpa, item.location].filter(Boolean).join(" · "),
      period: item.period,
      description: item.description,
      highlights: item.highlights,
    };
  }

  if ("company" in item) {
    return {
      title: item.company,
      subtitle: item.position,
      meta: item.location,
      period: item.period,
      description: item.description,
      highlights: item.highlights,
    };
  }

  if ("techStack" in item) {
    return {
      title: item.name,
      subtitle: item.role,
      meta: item.techStack.join(" · "),
      period: item.period,
      description: item.description,
      highlights: item.highlights,
    };
  }

  return {
    title: "name" in item ? item.name : "",
    subtitle: "issuer" in item ? item.issuer : "",
    meta: "",
    period: "date" in item ? item.date : "",
    description: "description" in item ? item.description : "",
    highlights: [],
  };
}

export function jsonResponse(data: unknown) {
  return new Response(
    JSON.stringify({
      code: 0,
      data,
      message: "SUCCESS",
    }),
    { headers: { "Content-Type": "application/json" }, status: 200 },
  );
}

export function createPdfFile(pages: string[][]): File {
  const objects = new Map<number, string>();
  const pageObjectIds = pages.map((_, index) => 4 + index * 2);
  const contentObjectIds = pages.map((_, index) => 5 + index * 2);

  objects.set(1, "<< /Type /Catalog /Pages 2 0 R >>");
  objects.set(
    2,
    `<< /Type /Pages /Kids [${pageObjectIds
      .map((objectId) => `${objectId} 0 R`)
      .join(" ")}] /Count ${pages.length} >>`,
  );
  objects.set(3, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");

  pages.forEach((lines, index) => {
    const pageObjectId = pageObjectIds[index];
    const contentObjectId = contentObjectIds[index];
    const stream = [
      "BT",
      "/F1 14 Tf",
      "18 TL",
      "72 760 Td",
      ...lines.flatMap((line, lineIndex) => [
        ...(lineIndex > 0 ? ["T*"] : []),
        `(${escapePdfString(line)}) Tj`,
      ]),
      "ET",
    ].join("\n");

    objects.set(
      pageObjectId,
      [
        "<< /Type /Page",
        "/Parent 2 0 R",
        "/MediaBox [0 0 612 792]",
        "/Resources << /Font << /F1 3 0 R >> >>",
        `/Contents ${contentObjectId} 0 R >>`,
      ].join(" "),
    );
    objects.set(
      contentObjectId,
      `<< /Length ${Buffer.byteLength(stream, "ascii")} >>\nstream\n${stream}\nendstream`,
    );
  });

  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  const objectCount = Math.max(...objects.keys());

  for (let objectId = 1; objectId <= objectCount; objectId += 1) {
    offsets[objectId] = Buffer.byteLength(pdf, "ascii");
    pdf += `${objectId} 0 obj\n${objects.get(objectId)}\nendobj\n`;
  }

  const xrefOffset = Buffer.byteLength(pdf, "ascii");
  pdf += `xref\n0 ${objectCount + 1}\n`;
  pdf += "0000000000 65535 f \n";
  for (let objectId = 1; objectId <= objectCount; objectId += 1) {
    pdf += `${String(offsets[objectId]).padStart(10, "0")} 00000 n \n`;
  }
  pdf += [
    "trailer",
    `<< /Size ${objectCount + 1} /Root 1 0 R >>`,
    "startxref",
    String(xrefOffset),
    "%%EOF",
    "",
  ].join("\n");

  return new NodeFile([Buffer.from(pdf, "ascii")], "public-entry.pdf", {
    type: "application/pdf",
  }) as unknown as File;
}

function escapePdfString(value: string) {
  return value
    .replaceAll("\\", "\\\\")
    .replaceAll("(", "\\(")
    .replaceAll(")", "\\)");
}

export function textItem(
  text: string,
  x: number,
  y: number,
  overrides: NonNullable<
    Parameters<typeof textContentToLinesForResumeImport>[0]["items"]
  >[number] = {},
) {
  return {
    str: text,
    transform: [1, 0, 0, 10, x, y],
    width: text.length * 10,
    height: 10,
    ...overrides,
  };
}

export function line(text: string, index: number, fontSize = 10): TextLine {
  return {
    text,
    page: 1,
    x: 40,
    y: 800 - index * 20,
    fontSize,
  };
}

export function positionedLine(
  text: string,
  y: number,
  x = 40,
  fontSize = 10,
  pageWidth?: number,
): TextLine {
  return {
    text,
    page: 1,
    ...(pageWidth ? { pageWidth } : {}),
    x,
    y,
    fontSize,
  };
}
