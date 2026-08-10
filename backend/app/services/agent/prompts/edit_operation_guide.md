Supported ResumeEditOperation shapes:
- replace_field {type,path,value} only for basic.headline or basic.summary; do not edit name/phone/email/location/avatar.
- update_item {type,sectionId,itemId,patch}; patch may contain only fields belonging to that section kind.
- insert_item {type,sectionId,item,index?}; item must match the target section kind.
- update_section {type,sectionId,patch:{title}}.
- insert_section {type,section:{section_type,title,items},index?}.
- delete_item {type,sectionId,itemId}.
- delete_section {type,sectionId}.
- reorder_sections {type,sectionIds}.
- reorder_items {type,sectionId,itemIds}.
Use existing IDs from the resume. If the target is unclear, call resume_lookup or resume_analysis first.
Canonical item fields by section kind:
- education: school, degree, major, gpa, location, period, description, highlights.
- experience: company, position, location, period, description, highlights. Work and internships share this kind; preserve the section title the user intends.
- project: name, role, techStack (string array), period, url, description, highlights.
- achievement: name, issuer, date, url, description. Use this when dates, issuers, or links should remain structured.
- simple_list: exactly one item with a rich-text `content` string. Put all skills, languages, interests, proficiency, scores, dates, or other compact details inside that content, preferably as `<ul><li>...</li></ul>`. Update this item; never insert, delete, split, merge, move, or reorder simple_list items.

Keep identity, date, metadata, prose, and bullet fields in their own lanes. Do not repeat structured fields in description or highlights. Highlights contain concrete actions, solutions, outcomes, and impact. Description is one short background sentence and may be empty.

Section rules:
- Allowed section_type values are: {section_kind_values}.
{section_label_lines}
- Every section has a user-visible title. Section kind chooses the editor/data shape; title expresses user meaning.
- Use experience for both work and internship sections.
- Use achievement for structured awards/certificates. If the user wants only compact award/certificate lines, simple_list is also valid.
- Use simple_list for skills, languages, interests, self-evaluation, or any other compact list. Set title to Skills, Languages, or the user's requested name; do not create separate skill/language kinds or multiple items.
- update_section can rename title only. It cannot change kind because item shapes differ.
- Move items only between sections of the same kind.
