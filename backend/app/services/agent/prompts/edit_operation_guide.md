Supported ResumeEditOperation shapes:
- replace_field {type,path,value} only for basic.headline, basic.location, or basic.summary; do not edit name/phone/email/avatar.
- update_item {type,sectionId,itemId,patch:{title,subtitle,meta,period,description,highlights}}.
- insert_item {type,sectionId,item,index?}.
- update_section {type,sectionId,patch:{section_type,layout,customTitle}}.
- insert_section {type,section:{section_type,layout,customTitle,items},index?}.
- delete_item {type,sectionId,itemId}.
- delete_section {type,sectionId}.
- reorder_sections {type,sectionIds}.
- reorder_items {type,sectionId,itemIds}.
Use existing IDs from the resume. If the target is unclear, call resume_analysis first.
basic.location is write-only: set it only when the user explicitly provides the desired value. Never infer or claim the current location from resume context.

Field filling rules:
- title: only the project name, company name, school name, certificate name, or award name.
- subtitle: only the position, role, major, degree, or identity information.
- meta: only tech stack, GPA, location, organization, or other compact metadata.
- period: only the time range. The user's "date" field maps to period.
- description: one short background sentence only; it may be empty.
- highlights: concrete actions, technical solutions, outcomes, and impact only.

Do not repeat title, subtitle, period/date, or meta content in highlights.
Do not fully repeat title, period/date, role, or tech stack in description.
If the original input is one mixed paragraph, split it into the matching fields first, then generate highlights.

Section rules:
Use only standard resume section types. Do not invent temporary section titles such as role-related projects, relevant experience, or core projects.
Allowed section_type values are: {section_kind_values}.
{section_label_lines}

If content is a project, put it under project.
If content is work or internship, put it under work or internship.
If the content is resume-relevant but does not fit a specific standard section, use other.
Use custom only when the user explicitly needs a named custom section that cannot map to a standard type, and explain why in the edit reason.
