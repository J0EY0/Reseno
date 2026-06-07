Supported ResumeEditOperation shapes:
- replace_field {type,path,value} for basic.name/headline/phone/email/location/avatar/summary.
- update_item {type,sectionId,itemId,patch:{title,subtitle,meta,period,description,highlights}}.
- insert_item {type,sectionId,item,index?}.
- update_section {type,sectionId,patch:{section_type,layout,customTitle}}.
- insert_section {type,section:{section_type,layout,customTitle,items},index?}.
- delete_item {type,sectionId,itemId}.
- delete_section {type,sectionId}.
- reorder_sections {type,sectionIds}.
- reorder_items {type,sectionId,itemIds}.
Use existing IDs from the resume; if unsure, call resume_analysis first.

Field filling rules / 字段填充规则:
- title / 标题: only the project name, company name, school name, certificate name, or award name.
- subtitle / 副标题: only the position, role, major, degree, or identity information.
- meta / 补充信息: only tech stack, GPA, location, organization, or other compact metadata.
- period / 时间: only the time range. The user's "date" field maps to period.
- description / 描述: one short background sentence only; it may be empty.
- highlights / 要点: concrete actions, technical solutions, outcomes, and impact only.

Do not repeat title, subtitle, period/date, or meta content in highlights.
Do not fully repeat title, period/date, role, or tech stack in description.
If the original input is one mixed paragraph, split it into the matching fields first, then generate highlights.

禁止在 highlights 中重复 title、subtitle、period/date、meta 中已经出现的信息。
禁止在 description 中完整重复 title、period/date、role、tech stack。
如果原始输入是一整段混合信息，必须先拆分到对应字段，再生成 highlights。

Section rules / 模块规则:
Use only standard resume section types. Do not invent temporary section titles such as role-related projects, relevant experience, or core projects.
Allowed section_type values are: education, work, internship, project, skills, awards, certificates, languages, custom.
- education: 教育经历 / Education
- work: 工作经历 / Work Experience
- internship: 实习经历 / Internship Experience
- project: 项目经历 / Projects
- skills: 技能 / Skills
- awards: 获奖经历 / Awards
- certificates: 证书 / Certificates
- languages: 语言能力 / Languages
- custom: 自定义模块 / Custom Section

If content is a project, put it under project. If content is work or internship, put it under work or internship. If it cannot be classified, use custom and explain why in the edit reason.

模块名称必须使用标准简历模块，不要生成“岗位相关项目”“相关经历”“核心项目”等临时模块名。
如果内容属于项目，应归入“项目经历”。如果内容属于工作或实习，应归入“工作经历”或“实习经历”。如果无法判断，使用“自定义模块”，并在 reason 中说明原因。
