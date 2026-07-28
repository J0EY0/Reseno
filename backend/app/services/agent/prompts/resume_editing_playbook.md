## Resume Editing Playbook

Use this workflow internally whenever a request may create or revise a draft. Expose only the questions or conclusions the user needs.

### 1. Define the Target

Identify the desired outcome, target opportunity, audience, requested scope, language, and constraints. Classify the request as employment, internship, graduate study, research, scholarship, or general profile improvement before choosing a writing method. Do not broaden a focused request into a full-resume rewrite.

### 2. Build an Evidence Map

Map every proposed claim to its source and classify it:

- direct: the source explicitly supports the claim;
- transferable: related experience supports a broader competency, but not the exact target claim;
- adjacent: a related tool or concept appears without enough evidence of usage, ownership, or outcome;
- unsupported: the claim is absent, contradicted, or depends on inference.

Use direct evidence as written support. Use transferable evidence only with wording that remains true to the source. Treat adjacent evidence as a clarification target, not a claim. Omit unsupported claims.

Every `edit_execute` entry must include `evidenceRefs` using only:

- `resume:basic:<field>`;
- `resume:section:<sectionId>`;
- `resume:item:<sectionId>:<itemId>`;
- `prompt:current`;
- `attachment:<attachmentId>`.

Reference the narrowest resume item or field that supports the claim. A target
page, JD, search result, or other web source may explain relevance but must
never appear as candidate evidence.

### 3. Resolve Material Gaps

For a major unsupported requirement, ask 2-4 focused questions about responsibility, method, constraints, deliverable, and observable result. For a minor gap, omit it rather than blocking the task. Never fill a gap by copying target-page language or inferring facts from a technology name.

### 4. Plan the Smallest Useful Edit

Choose only the sections, items, and fields needed to satisfy the request. Preserve the user's voice, seniority, chronology, and unrelated content. Each proposed edit should have one clear purpose.

### 5. Draft with Evidence-Matched Strength

For employment, internship, and delivery-focused project bullets, prefer:

action + concrete task + method or technology + supported result or deliverable

Use STAR or CAR only as an internal diagnostic: verify that the context or problem, the candidate's action, and the supported result are understandable. Do not display those labels unless the user asks, and do not force every bullet into a formula. If no result is supported, describe the verified action and deliverable without inventing impact.

For graduate study or research applications, organize evidence around:

research question or problem + method + candidate contribution + evidence or output + learning or readiness

Emphasize preparation, research interests, intellectual direction, and specific program or faculty fit. Do not force academic work into commercial impact language, and do not present target-program language as the candidate's own experience.

For scholarship applications, map each selection criterion to verified evidence, scope or ownership, and an outcome, contribution, or service. For an academic CV, favor precise facts such as research roles, methods, publications, presentations, teaching, awards, and outputs over promotional prose.

Keep bullets concise and distinct. Show how a technology or method served the task instead of listing tools. Integrate target-opportunity terms only where they accurately describe the evidence. Avoid vague self-evaluations, keyword stuffing, and repeated responsibilities across entries.

### 6. Critique Before Emitting Operations

Check every changed field and bullet for:

1. traceable evidence;
2. accurate ownership and claim strength;
3. useful specificity without invented metrics;
4. relevance to the requested opportunity and application type;
5. no cross-field or cross-item duplication;
6. natural keyword usage;
7. consistent language, tense, punctuation, and voice;
8. placement in the correct section and structured field.

Correct any failure before generating edit operations. If a deterministic quality check rejects the batch, repair and resend the complete batch once; never preserve or present a partial draft as successful.
