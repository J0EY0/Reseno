import type { AppMessages } from "@/i18n";
import { serializeListItemsToHtml } from "@/lib/rich-text";
import { getBuiltinTemplateStarter } from "@/lib/template-presets";
import type {
  AchievementItem,
  EducationItem,
  ExperienceItem,
  ProjectItem,
  PublicationItem,
  ResumeData,
  ResumeSectionOf,
  ResumeTemplateDefinition,
} from "@/types/resume";

export const TEMPLATE_PREVIEW_SCENARIOS = [
  "earlyCareer",
  "experienced",
  "executive",
  "research",
] as const;

export type TemplatePreviewScenario =
  (typeof TEMPLATE_PREVIEW_SCENARIOS)[number];

export type TemplatePreviewResumes = Record<TemplatePreviewScenario, ResumeData>;

type PreviewSamples = AppMessages["templatePreviewSamples"];
type PreviewBasicSample = PreviewSamples[TemplatePreviewScenario]["basic"];
type EducationSample =
  | PreviewSamples["earlyCareer"]["education"]
  | PreviewSamples["experienced"]["education"]
  | PreviewSamples["executive"]["education"]
  | PreviewSamples["research"]["education"];
type ExperienceSample =
  | PreviewSamples["earlyCareer"]["internship"]
  | PreviewSamples["experienced"]["experiences"][number]
  | PreviewSamples["executive"]["experiences"][number]
  | PreviewSamples["research"]["researchExperiences"][number]
  | PreviewSamples["research"]["teachingExperience"];
type ProjectSample =
  | PreviewSamples["earlyCareer"]["project"]
  | PreviewSamples["experienced"]["project"]
  | PreviewSamples["executive"]["project"];
type PublicationSample = PreviewSamples["research"]["publications"][number];
type AchievementSample =
  | PreviewSamples["earlyCareer"]["achievement"]
  | PreviewSamples["experienced"]["achievement"]
  | PreviewSamples["executive"]["achievements"][number]
  | PreviewSamples["research"]["achievements"][number];
type SkillSample =
  | PreviewSamples["earlyCareer"]["skills"][number]
  | PreviewSamples["experienced"]["skills"][number]
  | PreviewSamples["executive"]["skills"][number]
  | PreviewSamples["research"]["skills"][number];

function createAvatarPlaceholder(label: string) {
  const safeLabel = label.replaceAll('"', "&quot;");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="240" height="300" data-resumate-avatar-placeholder="true" data-placeholder-label="${safeLabel}"></svg>`;

  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function createBasicInfo(
  idPrefix: string,
  sample: PreviewBasicSample,
  t: AppMessages,
  showAvatar: boolean,
) {
  return {
    name: sample.name,
    headline: sample.headline,
    phone: sample.phone,
    email: sample.email,
    location: sample.location,
    avatar: showAvatar
      ? createAvatarPlaceholder(t.resumePreviewAvatarPlaceholder)
      : "",
    summary: sample.summary,
    customFields: [
      {
        id: `${idPrefix}-website`,
        type: "url" as const,
        label: sample.websiteLabel,
        value: sample.website,
      },
    ],
  };
}

function createEducationItem(id: string, sample: EducationSample): EducationItem {
  return {
    id,
    school: sample.school,
    degree: sample.degree,
    major: sample.major,
    gpa: sample.gpa,
    location: sample.location,
    period: sample.period,
    description: sample.description,
    highlights: sample.highlights,
  };
}

function createExperienceItem(
  id: string,
  sample: ExperienceSample,
): ExperienceItem {
  return {
    id,
    company: sample.company,
    position: sample.position,
    location: sample.location,
    period: sample.period,
    description: sample.description,
    highlights: sample.highlights,
  };
}

function createProjectItem(id: string, sample: ProjectSample): ProjectItem {
  return {
    id,
    name: sample.name,
    role: sample.role,
    techStack: sample.techStack,
    period: sample.period,
    url: "",
    description: sample.description,
    highlights: sample.highlights,
  };
}

function createAchievementItem(
  id: string,
  sample: AchievementSample,
): AchievementItem {
  return {
    id,
    name: sample.name,
    issuer: sample.issuer,
    date: sample.date,
    url: "",
    description: sample.description,
  };
}

function createPublicationItem(
  id: string,
  sample: PublicationSample,
): PublicationItem {
  return {
    id,
    title: sample.title,
    authors: sample.authors,
    venue: sample.venue,
    date: sample.date,
    url: sample.url,
    description: sample.description,
  };
}

function createSkillsSection(
  idPrefix: string,
  title: string,
  skills: readonly SkillSample[],
  separator: string,
): ResumeSectionOf<"simple_list"> {
  return {
    id: `${idPrefix}-skills`,
    kind: "simple_list",
    title,
    items: [
      {
        id: `${idPrefix}-skills-content`,
        content: serializeListItemsToHtml(
          skills.map((item) => `${item.title}${separator}${item.subtitle}`),
        ),
      },
    ],
  };
}

function createEarlyCareerPreview(t: AppMessages): ResumeData {
  const sample = t.templatePreviewSamples.earlyCareer;
  const idPrefix = "preview-student";

  return {
    schemaVersion: 2,
    basic: createBasicInfo(idPrefix, sample.basic, t, true),
    sections: [
      {
        id: `${idPrefix}-education`,
        kind: "education",
        title: "",
        items: [
          createEducationItem(`${idPrefix}-education-1`, sample.education),
        ],
      },
      {
        id: `${idPrefix}-experience`,
        kind: "experience",
        title: sample.experienceSectionTitle,
        items: [
          createExperienceItem(`${idPrefix}-experience-1`, sample.internship),
        ],
      },
      {
        id: `${idPrefix}-projects`,
        kind: "project",
        title: sample.projectSectionTitle,
        items: [createProjectItem(`${idPrefix}-project-1`, sample.project)],
      },
      {
        id: `${idPrefix}-achievements`,
        kind: "achievement",
        title: sample.achievementSectionTitle,
        items: [
          createAchievementItem(
            `${idPrefix}-achievement-1`,
            sample.achievement,
          ),
        ],
      },
      createSkillsSection(
        idPrefix,
        sample.skillsSectionTitle,
        sample.skills,
        t.templatePreviewListSeparator,
      ),
    ],
  };
}

function createExperiencedPreview(t: AppMessages): ResumeData {
  const sample = t.templatePreviewSamples.experienced;
  const idPrefix = "preview-career";

  return {
    schemaVersion: 2,
    basic: createBasicInfo(idPrefix, sample.basic, t, true),
    sections: [
      {
        id: `${idPrefix}-experience`,
        kind: "experience",
        title: sample.experienceSectionTitle,
        items: sample.experiences.map((experience, index) =>
          createExperienceItem(
            `${idPrefix}-experience-${index + 1}`,
            experience,
          ),
        ),
      },
      {
        id: `${idPrefix}-projects`,
        kind: "project",
        title: sample.projectSectionTitle,
        items: [createProjectItem(`${idPrefix}-project-1`, sample.project)],
      },
      {
        id: `${idPrefix}-achievements`,
        kind: "achievement",
        title: sample.achievementSectionTitle,
        items: [
          createAchievementItem(
            `${idPrefix}-achievement-1`,
            sample.achievement,
          ),
        ],
      },
      createSkillsSection(
        idPrefix,
        sample.skillsSectionTitle,
        sample.skills,
        t.templatePreviewListSeparator,
      ),
      {
        id: `${idPrefix}-education`,
        kind: "education",
        title: "",
        items: [
          createEducationItem(`${idPrefix}-education-1`, sample.education),
        ],
      },
    ],
  };
}

function createExecutivePreview(t: AppMessages): ResumeData {
  const sample = t.templatePreviewSamples.executive;
  const idPrefix = "preview-executive";

  return {
    schemaVersion: 2,
    basic: createBasicInfo(idPrefix, sample.basic, t, true),
    sections: [
      {
        id: `${idPrefix}-experience`,
        kind: "experience",
        title: sample.experienceSectionTitle,
        items: sample.experiences.map((experience, index) =>
          createExperienceItem(
            `${idPrefix}-experience-${index + 1}`,
            experience,
          ),
        ),
      },
      {
        id: `${idPrefix}-projects`,
        kind: "project",
        title: sample.projectSectionTitle,
        items: [createProjectItem(`${idPrefix}-project-1`, sample.project)],
      },
      {
        id: `${idPrefix}-achievements`,
        kind: "achievement",
        title: sample.achievementSectionTitle,
        items: sample.achievements.map((achievement, index) =>
          createAchievementItem(
            `${idPrefix}-achievement-${index + 1}`,
            achievement,
          ),
        ),
      },
      createSkillsSection(
        idPrefix,
        sample.skillsSectionTitle,
        sample.skills,
        t.templatePreviewListSeparator,
      ),
      {
        id: `${idPrefix}-education`,
        kind: "education",
        title: "",
        items: [
          createEducationItem(`${idPrefix}-education-1`, sample.education),
        ],
      },
    ],
  };
}

function createResearchPreview(t: AppMessages): ResumeData {
  const sample = t.templatePreviewSamples.research;
  const idPrefix = "preview-research";

  return {
    schemaVersion: 2,
    basic: createBasicInfo(idPrefix, sample.basic, t, false),
    sections: [
      {
        id: `${idPrefix}-education`,
        kind: "education",
        title: "",
        items: [
          createEducationItem(`${idPrefix}-education-1`, sample.education),
        ],
      },
      {
        id: `${idPrefix}-experience`,
        kind: "experience",
        title: sample.researchSectionTitle,
        items: sample.researchExperiences.map((experience, index) =>
          createExperienceItem(
            `${idPrefix}-experience-${index + 1}`,
            experience,
          ),
        ),
      },
      {
        id: `${idPrefix}-publications`,
        kind: "publication",
        title: sample.publicationSectionTitle,
        items: sample.publications.map((publication, index) =>
          createPublicationItem(
            `${idPrefix}-publication-${index + 1}`,
            publication,
          ),
        ),
      },
      {
        id: `${idPrefix}-teaching`,
        kind: "experience",
        title: sample.teachingSectionTitle,
        items: [
          createExperienceItem(
            `${idPrefix}-teaching-1`,
            sample.teachingExperience,
          ),
        ],
      },
      {
        id: `${idPrefix}-achievements`,
        kind: "achievement",
        title: sample.achievementSectionTitle,
        items: sample.achievements.map((achievement, index) =>
          createAchievementItem(
            `${idPrefix}-achievement-${index + 1}`,
            achievement,
          ),
        ),
      },
      createSkillsSection(
        idPrefix,
        sample.skillsSectionTitle,
        sample.skills,
        t.templatePreviewListSeparator,
      ),
    ],
  };
}

export function createTemplatePreviewResumes(
  t: AppMessages,
): TemplatePreviewResumes {
  // These fixtures stay outside template settings and workspace persistence so
  // previewing a scenario can never modify user data.
  return {
    earlyCareer: createEarlyCareerPreview(t),
    experienced: createExperiencedPreview(t),
    executive: createExecutivePreview(t),
    research: createResearchPreview(t),
  };
}

export function getTemplatePreviewResume(
  previewResumes: TemplatePreviewResumes,
  template: Pick<ResumeTemplateDefinition, "preset">,
) {
  return previewResumes[getBuiltinTemplateStarter(template.preset)];
}
