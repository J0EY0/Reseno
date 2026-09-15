import type { ResumeData } from "@/types/resume";

export function createResume(): ResumeData {
  return {
    schemaVersion: 2,
    basic: {
      name: "Original name",
      headline: "Engineer",
      phone: "",
      email: "",
      location: "",
      avatar: "",
      summary: "Original summary",
      customFields: [],
    },
    sections: [
      {
        id: "education",
        kind: "education",
        title: "Education",
        items: [],
      },
    ],
  };
}
