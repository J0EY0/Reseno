import { createId } from "@/lib/resume";

import type { TextLine } from "./pdf-text-extraction";
import {
  PDF_IMPORT_PROFILE,
  looksLikePeriodLine,
  median,
  type ResumeImportLexiconContext,
} from "./parser-config";
import {
  countTextGraphemes,
  joinWrappedLines,
  normalizeLexiconTerm,
  normalizeMatchingText,
  normalizeWhitespace,
  splitLabeledValue,
} from "./text-heuristics";

const CONTACT_TOKEN_SEPARATOR = /[|｜·•]/;
const EMAIL_PATTERN = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i;
const PHONE_PATTERN = /(?:\+?\d[\d\s-]{6,}\d)/;
const YEAR_RANGE_PATTERN =
  /^\d{4}(?:0[1-9]|1[0-2])?\s*[-–—]\s*\d{4}(?:0[1-9]|1[0-2])?$/;
const DOMAIN_PATTERN = /\b[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:\/\S*)?\b/i;
const WEB_CONTACT_PATTERN = /^(?:[a-z0-9-]+\.)+[a-z]{2,}(?:\/\S*)?$/i;
export function hasMeaningfulResumeText(lines: TextLine[]) {
  const normalizedLines = lines
    .map((line) => normalizeMatchingText(line.text))
    .filter(Boolean);
  if (normalizedLines.some(looksLikeContactLine)) {
    return true;
  }

  return (
    normalizedLines.filter((line) => /\p{L}/u.test(line)).length >=
    PDF_IMPORT_PROFILE.text.minMeaningfulLines
  );
}
export function extractBasicInfo(
  lines: TextLine[],
  lexiconContext: ResumeImportLexiconContext,
  includeSummary: boolean,
) {
  const rawTextLines = lines.map((line) => line.text);
  const name = inferName(rawTextLines, lexiconContext);
  const bodyFontSize = median(
    lines.map((line) => line.fontSize).filter(Boolean),
  );
  const semanticLines = lines.filter(
    (line) =>
      !looksLikeBasicFieldLabel(line, name, bodyFontSize, lexiconContext),
  );
  const textLines = semanticLines.map((line) => line.text);
  const joined = normalizeMatchingText(textLines.join(" "));
  const email = joined.match(EMAIL_PATTERN)?.[0] ?? "";
  const phone = extractPhone(
    textLines.slice(0, PDF_IMPORT_PROFILE.text.contactScanLineLimit),
  );
  const location = extractLocation(lines, name, bodyFontSize, lexiconContext);
  const contactIndexes = textLines
    .map((line, index) => (looksLikeContactLine(line) ? index : -1))
    .filter((index) => index >= 0);
  const firstContactIndex = contactIndexes[0] ?? -1;
  const lastContactIndex = contactIndexes.at(-1) ?? -1;
  const nameIndex = textLines.findIndex(
    (line) => normalizeMatchingText(line) === name,
  );
  const contentWithoutContacts = rawTextLines.filter(
    (line) =>
      normalizeMatchingText(line) !== name &&
      !lexiconContext.documentTitleTerms.has(normalizeLexiconTerm(line)),
  );
  const headlineLines =
    firstContactIndex >= 0
      ? textLines.slice(nameIndex + 1, firstContactIndex)
      : contentWithoutContacts.slice(0, 1);
  const summaryLines = includeSummary
    ? (lastContactIndex >= 0
        ? textLines.slice(lastContactIndex + 1)
        : contentWithoutContacts.slice(1)
      ).filter((line) => line !== location)
    : [];
  const customFields = extractCustomContactFields(textLines);
  const representedLines = new Set(
    [...headlineLines, ...summaryLines, name, location].map(
      normalizeMatchingText,
    ),
  );
  const contactValues = new Set(
    [name, email, phone, location, ...customFields.map((field) => field.value)]
      .map(normalizeMatchingText)
      .filter(Boolean),
  );
  const unclassifiedLines = lines.flatMap((line) => {
    if (
      representedLines.has(normalizeMatchingText(line.text)) ||
      lexiconContext.documentTitleTerms.has(normalizeLexiconTerm(line.text))
    ) {
      return [];
    }
    if (looksLikeContactLine(line.text)) {
      const remaining = line.text
        .split(CONTACT_TOKEN_SEPARATOR)
        .map((token) => {
          let value = normalizeMatchingText(stripLeadingContactLabel(token));
          for (const contact of contactValues) {
            const escaped = contact.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
            value = value.replace(
              new RegExp(
                `(?<![\\p{L}\\p{N}])${escaped}(?![\\p{L}\\p{N}])`,
                "giu",
              ),
              "",
            );
          }
          return normalizeWhitespace(value);
        })
        .filter(
          (value) =>
            /[\p{L}\p{N}]/u.test(value) &&
            !/^[\p{L}\p{M}\s]+[:：]$/u.test(value),
        );
      const text = remaining.join(" | ");
      return text ? [{ ...line, text }] : [];
    }
    return [line];
  });

  return {
    basic: {
      name,
      headline: joinWrappedLines(headlineLines),
      phone,
      email,
      location,
      avatar: "",
      summary: joinWrappedLines(summaryLines),
      customFields,
    },
    unclassifiedLines,
  };
}

function looksLikeContactLine(line: string) {
  const normalized = normalizeMatchingText(line);
  return (
    EMAIL_PATTERN.test(normalized) ||
    looksLikePhoneToken(normalized) ||
    line
      .split(CONTACT_TOKEN_SEPARATOR)
      .map(stripLeadingContactLabel)
      .some(looksLikeWebContactToken)
  );
}

function extractCustomContactFields(lines: string[]) {
  const fields: Array<{
    id: string;
    type: "url";
    label: string;
    value: string;
  }> = [];
  const seen = new Set<string>();

  for (const line of lines.slice(
    0,
    PDF_IMPORT_PROFILE.text.contactScanLineLimit,
  )) {
    const tokens = line
      .split(CONTACT_TOKEN_SEPARATOR)
      .map(normalizeWhitespace)
      .filter(Boolean);

    for (const token of tokens) {
      const isBareWebContact = looksLikeWebContactToken(token);
      const labeledValue = isBareWebContact
        ? null
        : splitLabeledValue(
            token,
            PDF_IMPORT_PROFILE.text.maxShortLabelGraphemes,
          );
      const label = isBareWebContact
        ? deriveWebContactLabel(token)
        : (labeledValue?.label ?? "");
      const value = isBareWebContact ? token : (labeledValue?.value ?? "");
      const normalizedValue = normalizeMatchingText(value);
      const dedupeKey = normalizedValue.toLowerCase();
      if (
        (!isBareWebContact && !looksLikeShortLabel(label)) ||
        !looksLikeWebContactToken(normalizedValue) ||
        seen.has(dedupeKey)
      ) {
        continue;
      }

      seen.add(dedupeKey);
      fields.push({
        id: createId("field"),
        type: "url",
        label,
        value: normalizedValue,
      });
    }
  }

  return fields;
}

function extractPhone(lines: string[]) {
  const matcher = new RegExp(PHONE_PATTERN.source, "g");
  for (const line of lines) {
    const normalized = normalizeMatchingText(line);
    for (const match of normalized.matchAll(matcher)) {
      const candidate = normalizeWhitespace(match[0] ?? "");
      if (looksLikePhoneToken(candidate)) {
        return candidate;
      }
    }
  }
  return "";
}

function looksLikePhoneToken(value: string) {
  const normalized = normalizeMatchingText(value).trim();
  const candidate = normalized.match(PHONE_PATTERN)?.[0]?.trim() ?? "";
  return Boolean(candidate) && !YEAR_RANGE_PATTERN.test(candidate);
}

function deriveWebContactLabel(value: string) {
  const normalized = normalizeMatchingText(value);
  try {
    const url = new URL(
      /^https?:\/\//i.test(normalized) ? normalized : `https://${normalized}`,
    );
    return url.hostname.replace(/^www\./i, "") || normalized;
  } catch {
    return normalized.split(/[/?#]/, 1)[0] ?? normalized;
  }
}
function extractLocation(
  lines: TextLine[],
  name: string,
  bodyFontSize: number,
  lexiconContext: ResumeImportLexiconContext,
) {
  // Keep this conservative: a wrong full contact line is more damaging than
  // an empty location field. Candidate tokens are only considered after the
  // same contact line has already exposed an email, phone, or web token; this
  // avoids treating a headline before the contact details as a location.
  for (const line of contactLines(lines)) {
    let sawContactToken = false;
    const locationCandidates: string[] = [];
    const tokens = line.text
      .split(CONTACT_TOKEN_SEPARATOR)
      .map(stripLeadingContactLabel)
      .map(normalizeWhitespace)
      .filter(Boolean);

    for (const token of tokens) {
      if (looksLikeContactToken(token)) {
        sawContactToken = true;
        continue;
      }

      if (sawContactToken && looksLikeLocationToken(token, name)) {
        return token;
      }

      if (!sawContactToken && looksLikePrefixLocationToken(token, name)) {
        locationCandidates.push(token);
      }
    }

    if (
      locationCandidates.length ===
      PDF_IMPORT_PROFILE.text.maxStandaloneLocationTokens
    ) {
      return locationCandidates[0] ?? "";
    }
  }

  const lastContactIndex = lines.findLastIndex((line) =>
    looksLikeContactLine(line.text),
  );
  if (lastContactIndex >= 0) {
    const candidates = lines.slice(
      lastContactIndex + 1,
      lastContactIndex +
        1 +
        PDF_IMPORT_PROFILE.text.standaloneLocationLookaheadLines,
    );
    for (const [index, line] of candidates.entries()) {
      const nextLine = candidates[index + 1];
      if (
        looksLikeLocationToken(line.text, name) &&
        (isStrongStandaloneLocation(line.text) ||
          (nextLine !== undefined &&
            looksLikeBasicFieldLabel(
              nextLine,
              name,
              bodyFontSize,
              lexiconContext,
            )))
      ) {
        return line.text;
      }
    }
  }

  return "";
}

function contactLines(lines: TextLine[]) {
  return lines
    .slice(0, PDF_IMPORT_PROFILE.text.contactScanLineLimit)
    .filter((line) => looksLikeContactLine(line.text));
}

function looksLikeBasicFieldLabel(
  line: TextLine,
  name: string,
  bodyFontSize: number,
  lexiconContext: ResumeImportLexiconContext,
) {
  return (
    line.text !== name &&
    countTextGraphemes(line.text) <=
      PDF_IMPORT_PROFILE.text.maxShortLabelGraphemes &&
    line.fontSize >=
      bodyFontSize * PDF_IMPORT_PROFILE.layout.basicFieldLabelScale &&
    !looksLikeContactLine(line.text) &&
    !looksLikePeriodLine(line.text, lexiconContext)
  );
}

function isStrongStandaloneLocation(value: string) {
  const normalized = normalizeWhitespace(value);
  const cjkText = normalized.replace(/\s+/g, "");
  return (
    /[/,，]/.test(normalized) ||
    (countTextGraphemes(cjkText) >=
      PDF_IMPORT_PROFILE.text.minCjkLocationGraphemes &&
      countTextGraphemes(cjkText) <=
        PDF_IMPORT_PROFILE.text.maxPrefixCjkLocationGraphemes &&
      /^[\p{Script=Han}]+$/u.test(cjkText))
  );
}

function stripLeadingContactLabel(token: string) {
  if (/^https?:\/\//i.test(token)) {
    return token;
  }

  const parts = token.split(/[:：]/);
  if (parts.length < 2) {
    return token;
  }

  const [label, ...rest] = parts;
  return looksLikeShortLabel(label ?? "") ? rest.join(":") : token;
}

export function looksLikeShortLabel(value: string) {
  const normalized = normalizeWhitespace(value);
  const matchingText = normalizeMatchingText(normalized);
  return (
    countTextGraphemes(normalized) > 0 &&
    countTextGraphemes(normalized) <=
      PDF_IMPORT_PROFILE.text.maxShortLabelGraphemes &&
    !EMAIL_PATTERN.test(matchingText) &&
    !looksLikePhoneToken(matchingText) &&
    !DOMAIN_PATTERN.test(matchingText)
  );
}

function looksLikeContactToken(value: string) {
  const normalized = normalizeMatchingText(value);
  return (
    EMAIL_PATTERN.test(normalized) ||
    looksLikePhoneToken(normalized) ||
    looksLikeWebContactToken(normalized)
  );
}

function looksLikeWebContactToken(value: string) {
  const normalized = normalizeMatchingText(value);
  return (
    /^https?:\/\//i.test(normalized) ||
    /^www\./i.test(normalized) ||
    WEB_CONTACT_PATTERN.test(normalized)
  );
}

function looksLikeLocationToken(token: string, name: string) {
  const normalized = normalizeWhitespace(token);
  const matchingText = normalizeMatchingText(normalized);
  if (!normalized || normalized === name) {
    return false;
  }

  if (
    EMAIL_PATTERN.test(matchingText) ||
    looksLikePhoneToken(matchingText) ||
    looksLikeWebContactToken(matchingText)
  ) {
    return false;
  }

  if (/^\d+$/.test(normalized) || /[@\\]/.test(normalized)) {
    return false;
  }

  const chineseText = normalized.replace(/\s+/g, "");
  if (
    countTextGraphemes(chineseText) >=
      PDF_IMPORT_PROFILE.text.minCjkLocationGraphemes &&
    countTextGraphemes(chineseText) <=
      PDF_IMPORT_PROFILE.text.maxCjkLocationGraphemes &&
    /^[\p{Script=Han}]+$/u.test(chineseText)
  ) {
    return true;
  }

  return (
    countTextGraphemes(normalized) <=
      PDF_IMPORT_PROFILE.text.maxLocationGraphemes &&
    /^[\p{L}\p{M}][\p{L}\p{M} .,'’/-]+$/u.test(normalized) &&
    /[\s/,，]/.test(normalized)
  );
}

function looksLikePrefixLocationToken(token: string, name: string) {
  const normalized = normalizeWhitespace(token);
  const chineseText = normalized.replace(/\s+/g, "");

  if (chineseText !== normalized) {
    return looksLikeLocationToken(normalized, name);
  }

  return (
    looksLikeLocationToken(normalized, name) &&
    /^[\p{Script=Han}]+$/u.test(chineseText) &&
    countTextGraphemes(chineseText) <=
      PDF_IMPORT_PROFILE.text.maxPrefixCjkLocationGraphemes
  );
}

function inferName(
  lines: string[],
  lexiconContext: ResumeImportLexiconContext,
) {
  for (const line of lines.slice(0, PDF_IMPORT_PROFILE.text.maxNameScanLines)) {
    const normalized = normalizeMatchingText(
      line
        .replace(/[|｜·•].*$/, "")
        .replace(new RegExp(EMAIL_PATTERN, "gi"), "")
        .replace(new RegExp(PHONE_PATTERN, "g"), ""),
    );
    const normalizedTerm = normalizeLexiconTerm(normalized);
    if (
      normalized &&
      countTextGraphemes(normalized) <=
        PDF_IMPORT_PROFILE.text.maxNameGraphemes &&
      !lexiconContext.documentTitleTerms.has(normalizedTerm) &&
      !/[：:]/.test(normalized)
    ) {
      return normalized;
    }
  }

  return "";
}
