"""
Site Handlers Registry.
"""
from typing import List, Type
from .base import BaseSiteHandler, StoryInfo, ChapterItem, ChapterContent
from .wetruyen_truyenfull import TruyenFullFamilyHandler
from .universal import UniversalSiteHandler

REGISTERED_HANDLERS: List[BaseSiteHandler] = [
    TruyenFullFamilyHandler(),
    UniversalSiteHandler(),
]

def get_handler_for_url(url: str) -> BaseSiteHandler:
    """Find the best matching site handler for the specified URL."""
    for handler in REGISTERED_HANDLERS:
        if handler.match(url):
            return handler
    return UniversalSiteHandler()

