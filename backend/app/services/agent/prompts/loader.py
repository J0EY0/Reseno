from functools import cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent


@cache
def load_prompt(filename: str) -> str:
    """Load a checked-in prompt file once per process."""

    return (PROMPT_DIR / filename).read_text(encoding="utf-8").strip()


SYSTEM_PROMPTS = {
    "zh": load_prompt("system.zh.md"),
    "en": load_prompt("system.en.md"),
}

AGENT_INTENT_KEYWORDS = {
    "zh": (
        "简历",
        "履历",
        "jd",
        "岗位",
        "职位",
        "职责",
        "要求",
        "优化",
        "修改",
        "调整",
        "新增",
        "增加",
        "删除",
        "移除",
        "排序",
        "顺序",
        "模块",
        "项目",
        "实习",
        "教育",
        "经历",
        "技能",
        "关键词",
        "匹配",
        "预览",
        "草稿",
        "应用",
        "撤回",
        "求职",
        "面试",
    ),
    "en": (
        "resume",
        "cv",
        "jd",
        "job description",
        "role",
        "position",
        "requirement",
        "responsibility",
        "optimize",
        "improve",
        "rewrite",
        "edit",
        "revise",
        "add",
        "remove",
        "delete",
        "reorder",
        "section",
        "project",
        "experience",
        "education",
        "skill",
        "keyword",
        "match",
        "draft",
        "preview",
        "apply",
        "internship",
    ),
}

EDIT_OPERATION_GUIDE = load_prompt("edit_operation_guide.md")

DEFAULT_REACT_MAX_ITERATIONS = 5
MIN_REACT_MAX_ITERATIONS = 1
MAX_REACT_MAX_ITERATIONS = 8
