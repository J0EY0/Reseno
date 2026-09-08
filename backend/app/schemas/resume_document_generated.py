from __future__ import annotations

from typing import Literal, TypedDict

type NodeId = str


type InlineText = str


class CustomField(TypedDict):
    id: str
    type: Literal['email', 'phone', 'url', 'text']
    label: str
    value: str


class Basic(TypedDict):
    name: InlineText
    headline: InlineText
    phone: str
    email: str
    location: InlineText
    avatar: str
    summary: str
    customFields: list[CustomField]


class EducationItem(TypedDict):
    id: NodeId
    school: InlineText
    degree: InlineText
    major: InlineText
    gpa: InlineText
    location: InlineText
    period: InlineText
    description: InlineText
    highlights: list[str]


class ExperienceItem(TypedDict):
    id: NodeId
    company: InlineText
    position: InlineText
    location: InlineText
    period: InlineText
    description: InlineText
    highlights: list[str]


class ProjectItem(TypedDict):
    id: NodeId
    name: InlineText
    role: InlineText
    techStack: list[InlineText]
    period: InlineText
    url: str
    description: InlineText
    highlights: list[str]


class PublicationItem(TypedDict):
    id: NodeId
    title: InlineText
    authors: InlineText
    venue: InlineText
    date: InlineText
    url: str
    description: InlineText


class AchievementItem(TypedDict):
    id: NodeId
    name: InlineText
    issuer: InlineText
    date: InlineText
    url: str
    description: InlineText


class SimpleListItem(TypedDict):
    id: NodeId
    content: str


class EducationSection(TypedDict):
    id: NodeId
    kind: Literal['education']
    title: str
    items: list[EducationItem]


class ExperienceSection(TypedDict):
    id: NodeId
    kind: Literal['experience']
    title: str
    items: list[ExperienceItem]


class ProjectSection(TypedDict):
    id: NodeId
    kind: Literal['project']
    title: str
    items: list[ProjectItem]


class PublicationSection(TypedDict):
    id: NodeId
    kind: Literal['publication']
    title: str
    items: list[PublicationItem]


class AchievementSection(TypedDict):
    id: NodeId
    kind: Literal['achievement']
    title: str
    items: list[AchievementItem]


class SimpleListSection(TypedDict):
    id: NodeId
    kind: Literal['simple_list']
    title: str
    items: list[SimpleListItem]


type Section = (
    EducationSection
    | ExperienceSection
    | ProjectSection
    | PublicationSection
    | AchievementSection
    | SimpleListSection
)


class ResumeDocument(TypedDict):
    schemaVersion: Literal[2]
    basic: Basic
    sections: list[Section]
