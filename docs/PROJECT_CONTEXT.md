# Reseno Project Context

## 产品定位

Reseno 是一个融合 AI Agent 的简历制作工作台。当前阶段目标是持续打磨前端产品体验、数据结构、A4 渲染与导出链路，同时保持真实后端的领域职责清晰。

核心用户路径：

- 从简历列表创建、导入或打开简历。
- 在结构化编辑器里填写基本信息、教育经历、实习经历、项目经历和其他模块。
- 中间区域实时渲染真实 A4 简历预览。
- 通过模板系统调整简历外观。
- 通过 Agent 获取修改建议、关键词补充和知识准备建议。
- 导出 PDF。

## 设计原则

- A4 真实性优先：简历 DOM 和 PDF 导出保持真实 A4 尺寸，屏幕预览可以等比缩放。
- 结构化内容优先：简历内容保持字段化，不直接暴露任意 HTML，便于 ATS、模板切换和后端持久化。
- 模板可控自定义：模板允许调整布局、字体、颜色、背景和图片元素，但不破坏简历语义结构。
- API First：前端逻辑先走定义好的 API helper；业务数据通过真实后端读取和保存。
- shadcn/ui + Tailwind：界面组件优先使用 shadcn 风格和基础黑白配色，保持一致性。

## 技术概览

- 前端目录：`frontend`
- 技术栈：React、TypeScript、Vite、Tailwind CSS、shadcn/ui
- 路由：
  - `/login`
  - `/resume`
  - `/resume/:id`
  - `/templates`
  - `/template/:id`
  - `/trash`
  - `/models`
  - `/settings`
- 后端目录：`backend`
- 核心类型：`frontend/src/types/resume.ts`、`frontend/src/types/api.ts`
- API 入口：`frontend/src/lib/api-client.ts`

## 当前产品边界

已实现可运行的前端工作台和按职责拆分的后端数据链路：页面进入时只调用对应
的只读 page query，简历、版本、模板、模型配置和 Agent 会话由各自资源接口
读写，不再上传或下载整个 workspace 快照。真实模型推理的质量与稳定性、PDF
多页精确渲染和从文本/PDF 自动生成简历仍属于后续重点。
