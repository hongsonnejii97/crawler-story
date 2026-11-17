"""
Handler for 'Đọc Đêm' / shissf.com / truyentruyen.com SPA novel platform.
Stories and chapters are stored in static JSON files:
- Story index: /data/truyen.json
- Chapter content: /data/{slug}/{chapter_number}.json
"""
import re
import json
import zlib
import html
import urllib.parse
import logging
from typing import List, Optional, Dict, Any
from bs4 import BeautifulSoup

from .base import BaseSiteHandler, StoryInfo, ChapterItem, ChapterContent
from .universal import extract_slug_from_url

logger = logging.getLogger("DocDemHandler")


class DocDemHandler(BaseSiteHandler):
    name = "Đọc Đêm (SPA)"

    # In-memory cache for /data/truyen.json per domain to prevent re-downloading 6MB on each call
    _cache: Dict[str, List[Dict[str, Any]]] = {}

    def match(self, url: str) -> bool:
        netloc = urllib.parse.urlparse(url).netloc.lower()
        return any(d in netloc for d in ["shissf.com", "truyentruyen.com", "docdem"])

    def _get_base_url(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _get_truyen_data(self, url: str, fetcher: Any = None) -> List[Dict[str, Any]]:
        base_url = self._get_base_url(url)
        if base_url in self._cache:
            return self._cache[base_url]

        data_url = urllib.parse.urljoin(base_url, "/data/truyen.json")
        try:
            if fetcher:
                raw = fetcher.fetch(data_url)
            else:
                from ..fetcher import Fetcher
                raw = Fetcher().fetch(data_url)

            data = json.loads(raw)
            if isinstance(data, list):
                self._cache[base_url] = data
                return data
        except Exception as e:
            logger.error(f"Failed to fetch {data_url}: {e}")
        return []

    def _extract_target_slug(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.strip("/")
        m = re.search(r"truyen/([^/?#]+)", path)
        if m:
            return m.group(1)
        parts = [p for p in path.split("/") if p]
        return parts[-1] if parts else ""

    def _find_story(self, url: str, fetcher: Any = None) -> Optional[Dict[str, Any]]:
        target_slug = self._extract_target_slug(url)
        if not target_slug:
            return None

        data = self._get_truyen_data(url, fetcher)
        for s in data:
            if s.get("slug") == target_slug:
                return s

        # Substring / partial match fallback
        for s in data:
            s_slug = s.get("slug", "")
            if s_slug and (target_slug in s_slug or s_slug in target_slug):
                return s

        return None

    def extract_story_info(self, html_content: str, url: str, fetcher: Any = None) -> StoryInfo:
        story = self._find_story(url, fetcher)
        soup = BeautifulSoup(html_content, "html.parser")
        base_url = self._get_base_url(url)

        if story:
            title = story.get("title", "")
            author = story.get("author", "Không rõ")
            if not author or author.lower() in ["đang cập nhật", "updating", "chưa rõ"]:
                author = "Không rõ"
            desc = story.get("description", "")
            cover_path = story.get("cover", "")
            cover_url = urllib.parse.urljoin(base_url, cover_path) if cover_path else ""
            slug = story.get("slug") or extract_slug_from_url(url, title)
        else:
            og_title = soup.select_one('meta[property="og:title"]')
            title = og_title.get("content", "").replace("– Đọc Đêm", "").strip() if og_title else "Truyện Không Tên"
            og_desc = soup.select_one('meta[property="og:description"]')
            desc = og_desc.get("content", "").strip() if og_desc else ""
            og_img = soup.select_one('meta[property="og:image"]')
            cover_url = og_img.get("content", "").strip() if og_img else ""
            author = "Không rõ"
            slug = extract_slug_from_url(url, title)

        original_id = zlib.crc32(f"{base_url}/{slug}".encode("utf-8")) % 900000 + 10000

        return StoryInfo(
            title=title,
            url=url,
            original_id=original_id,
            slug=slug,
            author=author,
            description=desc,
            cover_url=cover_url
        )

    def extract_chapter_list(self, html_content: str, url: str, fetcher: Any = None) -> List[ChapterItem]:
        story = self._find_story(url, fetcher)
        if not story:
            return []

        base_url = self._get_base_url(url)
        slug = story.get("slug")
        num_chapters = story.get("chapters", 0)
        raw_titles = story.get("titles", [])
        story_title = story.get("title", "")

        chapters: List[ChapterItem] = []
        for i in range(1, num_chapters + 1):
            chap_url = f"{base_url}/data/{slug}/{i}.json"

            t = ""
            if i - 1 < len(raw_titles):
                t = (raw_titles[i - 1] or "").strip()

            if not t or t == story_title or not re.search(r"(?:chương|chap|hồi)\b", t, re.I):
                chap_title = f"Chương {i}"
                if t and t != story_title:
                    chap_title = f"Chương {i}: {t}"
            else:
                chap_title = t

            chapters.append(ChapterItem(
                index=i,
                title=chap_title,
                url=chap_url,
                slug=f"chuong-{i}"
            ))

        return chapters

    def extract_chapter_content(self, html_content: str, url: str, cleaner: Any) -> ChapterContent:
        content_json = None
        try:
            content_json = json.loads(html_content)
        except Exception:
            pass

        if not content_json and ("<div id=\"root\">" in html_content or "<!doctype" in html_content.lower()):
            m = re.search(r"/(?:data|truyen)/([^/]+)/(?:chuong-)?(\d+)(?:\.json)?", url)
            if m:
                slug = m.group(1)
                chap_num = m.group(2)
                base_url = self._get_base_url(url)
                data_url = f"{base_url}/data/{slug}/{chap_num}.json"
                from ..fetcher import Fetcher
                try:
                    txt = Fetcher().fetch(data_url)
                    content_json = json.loads(txt)
                except Exception as e:
                    logger.error(f"Error fetching {data_url}: {e}")

        clean_paras: List[str] = []
        title = ""
        chap_num = 1
        m_num = re.search(r"/(\d+)\.json", url) or re.search(r"/chuong-(\d+)", url)
        if m_num:
            chap_num = int(m_num.group(1))

        if content_json and isinstance(content_json, dict):
            title = content_json.get("title", "")
            raw_paragraphs = content_json.get("paragraphs", [])
            for p in raw_paragraphs:
                if isinstance(p, str):
                    p_clean = p.strip()
                    if p_clean and not cleaner.is_ad_line(p_clean):
                        clean_paras.append(p_clean)

        html_out = "\r\n".join(f"<p>{html.escape(p)}</p>" for p in clean_paras)

        return ChapterContent(
            title=title or f"Chương {chap_num}",
            url=url,
            paragraphs=clean_paras,
            html_content=html_out,
            slug=f"chuong-{chap_num}",
            number=chap_num
        )
