"""
Base Site Handler definition.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

@dataclass
class ChapterItem:
    index: int
    title: str
    url: str
    slug: str = ""
    date: str = ""

@dataclass
class StoryInfo:
    title: str
    url: str
    original_id: int = 0
    slug: str = ""
    author: str = "Không rõ"
    description: str = ""
    cover_url: str = ""
    chapters: List[ChapterItem] = field(default_factory=list)

@dataclass
class ChapterContent:
    title: str
    url: str
    paragraphs: List[str] = field(default_factory=list)
    html_content: str = ""
    original_id: int = 0
    number: int = 1
    slug: str = ""
    date: str = ""
    views: Optional[int] = None
    next_url: Optional[str] = None

class BaseSiteHandler:
    name: str = "Base"

    def match(self, url: str) -> bool:
        """Return True if this handler matches the given URL."""
        raise NotImplementedError

    def extract_story_info(self, html: str, url: str) -> StoryInfo:
        """Extract story metadata from the story overview page."""
        raise NotImplementedError

    def extract_chapter_list(self, html: str, url: str, fetcher: Any) -> List[ChapterItem]:
        """Extract all chapter links, navigating pagination if necessary."""
        raise NotImplementedError

    def extract_chapter_content(self, html: str, url: str, cleaner: Any) -> ChapterContent:
        """Extract chapter title, cleaned content paragraphs/HTML, and next chapter URL."""
        raise NotImplementedError
