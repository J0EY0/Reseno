"""Tool adapters hidden behind the resume-agent environment seam."""

from .attachments import AttachmentToolAdapter
from .web import WebToolAdapter

__all__ = ["AttachmentToolAdapter", "WebToolAdapter"]
