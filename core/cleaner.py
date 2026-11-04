"""
Ad Cleaner and Content Normalizer module.
Removes ads, banner tags, translator watermarks, donation requests, and site spam.
"""
import re
import html
from typing import List, Optional
from bs4 import BeautifulSoup, Tag

DEFAULT_AD_PHRASES = [
    r"đọc truyện tại\s+[a-zA-Z0-9.\-_/]+",
    r"truy cập\s+[a-zA-Z0-9.\-_/]+\s+để đọc",
    r"bản dịch\s+(độc quyền|thuộc về|chỉ có tại)",
    r"chương này được (dịch|viết|convert) bởi",
    r"nguồn truyện:\s+[a-zA-Z0-9.\-_/]+",
    r"ủng hộ (dịch giả|nhóm dịch|converter)",
    r"donate\s+(qua|cho|stk|momo|ngân hàng)",
    r"stk:\s*\d+",
    r"momo:\s*\d+",
    r"mời (các )?bạn tham gia (group|nhóm|fanpage)",
    r"like fanpage để theo dõi",
    r"tải app\s+[a-zA-Z0-9.\-_/]+\s+để đọc",
    r"chúc (bạn|các bạn) đọc truyện vui vẻ",
    r"mọi hành vi sao chép không xin phép",
    r"truy cập website\s+[a-zA-Z0-9.\-_/]+",
    r"theo dõi kênh telegram",
    r"zalo\.me/\S+",
    r"t\.me/\S+",
    r"facebook\.com/\S+",
    r"https?://[a-zA-Z0-9.\-_/]+",
    r"(truyenfull|tangthuvien|metruyencv|metruyenchu|dtruyen|wetruyen|sstruyen|wikidich|bachngocsach)\.(com|vn|net|org|vip)",
]

DEFAULT_REMOVE_TAGS = [
    "script", "style", "ins", "iframe", "noscript", "object", "embed",
    "svg", "canvas", "button", "input", "form", "select", "textarea"
]

DEFAULT_AD_SELECTORS = [
    ".ads", "#ads", ".ad-container", ".advertisement", ".quang-cao", ".banner",
    ".adsbygoogle", ".box-sponsor", ".fb-comments", ".social-share",
    ".nav-chapter", ".chapter-nav", ".btn-chapter-nav", ".box-notice",
    ".rating-box", ".donate-box", ".bottom-ads", ".top-ads"
]

class ContentCleaner:
    def __init__(self, custom_phrases: Optional[List[str]] = None, min_paragraph_length: int = 1):
        self.min_length = min_paragraph_length
        self.ad_regexes = []
        all_phrases = list(DEFAULT_AD_PHRASES)
        if custom_phrases:
            all_phrases.extend(custom_phrases)

        for p in all_phrases:
            try:
                self.ad_regexes.append(re.compile(p, re.IGNORECASE))
            except re.error:
                # If invalid regex, escape it as plain text match
                self.ad_regexes.append(re.compile(re.escape(p), re.IGNORECASE))

    def clean_html_tree(self, container: Tag) -> Tag:
        """Strip ad tags, scripts, banners and hidden elements from BeautifulSoup container."""
        # Remove standard garbage tags
        for tag_name in DEFAULT_REMOVE_TAGS:
            for el in container.find_all(tag_name):
                el.decompose()

        # Remove elements matching ad selectors
        for sel in DEFAULT_AD_SELECTORS:
            try:
                for el in container.select(sel):
                    el.decompose()
            except Exception:
                pass

        # Remove elements with class or id matching ad patterns
        for el in container.find_all(attrs={"class": re.compile(r"(^|\s|_|-)(ad|ads|banner|qc|quang-cao|sponsor)(\s|_|-|$)", re.I)}):
            el.decompose()

        for el in container.find_all(attrs={"id": re.compile(r"(^|\s|_|-)(ad|ads|banner|qc|quang-cao|sponsor)(\s|_|-|$)", re.I)}):
            el.decompose()

        # Convert <br> and <p> boundaries into newlines
        for br in container.find_all("br"):
            br.replace_with("\n")

        for p in container.find_all(["p", "div"]):
            p.append("\n")

        return container

    def is_ad_line(self, line: str) -> bool:
        """Check if a line matches any known advertisement pattern."""
        text = line.strip()
        if not text:
            return True

        if len(text) < self.min_length:
            return True

        for regex in self.ad_regexes:
            # If the entire line is mostly the ad pattern
            if regex.search(text):
                # If regex matches more than 50% of the line or the line is clearly a promo line
                match = regex.search(text)
                if match:
                    span_len = match.end() - match.start()
                    if span_len >= len(text) * 0.4 or len(text) < 120:
                        return True
        return False

    def clean_text_into_paragraphs(self, raw_text: str) -> List[str]:
        """Convert raw text into clean, ad-free list of paragraphs."""
        # Unescape HTML entities
        text = html.unescape(raw_text)

        # Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        lines = text.split("\n")
        paragraphs = []

        for line in lines:
            line = line.strip()
            # Collapse excessive internal spaces
            line = re.sub(r"[ \t]+", " ", line)

            if not line:
                continue

            if self.is_ad_line(line):
                continue

            paragraphs.append(line)

        return paragraphs

    def clean_container(self, container: Tag) -> List[str]:
        """Convenience method: takes a BeautifulSoup container tag and returns cleaned paragraphs."""
        cl_tree = self.clean_html_tree(container)
        raw_text = cl_tree.get_text()
        return self.clean_text_into_paragraphs(raw_text)

