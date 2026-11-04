"""
Universal Adaptive Site Handler.
Automatically detects and extracts novel information, chapter lists, and content from any website.
"""
import re
import urllib.parse
from typing import List, Optional, Any, Set
from bs4 import BeautifulSoup, Tag
from .base import BaseSiteHandler, StoryInfo, ChapterItem, ChapterContent

class UniversalSiteHandler(BaseSiteHandler):
    name = "Universal Auto-Detector"

    def match(self, url: str) -> bool:
        return True  # Fallback handler for all sites

    def extract_story_info(self, html: str, url: str) -> StoryInfo:
        soup = BeautifulSoup(html, "html.parser")

        # 1. Title Extraction
        title = ""
        # Try OpenGraph title
        og_title = soup.select_one('meta[property="og:title"]')
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()

        # Try H1
        if not title:
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text(strip=True)

        # Fallback to <title>
        if not title and soup.title:
            title = soup.title.get_text(strip=True)

        # Clean common site branding from title e.g. "Truyện A - Đọc tại Website B"
        title = re.sub(r"\s*[-|–]\s*(Đọc truyện|Truyện Full|Online|Tàng Thư Viện|Wattpad|WeTruyen|TruyenFull).*$", "", title, flags=re.IGNORECASE).strip()
        if not title:
            title = "Truyện Không Tên"

        # 2. Author Extraction
        author = "Không rõ"
        author_meta = soup.select_one('meta[name="author"], [itemprop="author"], .author')
        if author_meta:
            author = author_meta.get("content") or author_meta.get_text(strip=True)
        else:
            # Search for "Tác giả:" text pattern
            m = re.search(r"Tác giả\s*:\s*([^<\n\r,]+)", html, re.IGNORECASE)
            if m:
                author = m.group(1).strip()

        # Clean author if it has tags
        author = re.sub(r"<[^>]+>", "", author).strip() or "Không rõ"

        # 3. Description Extraction
        desc = ""
        og_desc = soup.select_one('meta[property="og:description"], meta[name="description"]')
        if og_desc and og_desc.get("content"):
            desc = og_desc["content"].strip()
        else:
            desc_tag = soup.select_one(".description, .desc, .summary, .story-desc, .intro, #description")
            if desc_tag:
                desc = desc_tag.get_text(strip=True)

        # 4. Cover URL
        cover_url = ""
        og_img = soup.select_one('meta[property="og:image"]')
        if og_img and og_img.get("content"):
            cover_url = urllib.parse.urljoin(url, og_img["content"].strip())

        return StoryInfo(
            title=title,
            url=url,
            author=author,
            description=desc,
            cover_url=cover_url
        )

    def extract_chapter_list(self, html: str, url: str, fetcher: Any = None) -> List[ChapterItem]:
        soup = BeautifulSoup(html, "html.parser")
        chapters: List[ChapterItem] = []
        seen_urls: Set[str] = set()

        # Check if the page itself is a chapter rather than story overview
        # If so, return at least this chapter
        is_chapter_page = bool(re.search(r"/(chuong|chapter|chap|hoi)-\d+", url, re.I))

        # Look for candidate links
        def _harvest_links(curr_soup: BeautifulSoup) -> List[ChapterItem]:
            items = []
            # Priority 1: standard chapter container
            containers = curr_soup.select(
                "#list-chapter, .list-chapter, .chapter-list, .list-chapters, "
                ".chapters, #chapters, .table-list, ul.list-chap, .box-chap"
            )
            candidate_links = []
            if containers:
                for c in containers:
                    candidate_links.extend(c.find_all("a", href=True))
            else:
                # Priority 2: all <a> tags that match chapter URL pattern or text
                for a in curr_soup.find_all("a", href=True):
                    href = a.get("href", "")
                    text = a.get_text(strip=True)
                    # Exclude anchors, javascript, home
                    if href.startswith("#") or "javascript:" in href or href == "/":
                        continue
                    if re.search(r"(chuong|chapter|chap|hoi)[-_/]?\d+", href, re.I) or re.search(r"^(Chương|Hồi|Chap|Chapter)\s+\d+", text, re.I):
                        candidate_links.append(a)

            for a in candidate_links:
                href = a.get("href", "")
                title = a.get_text(strip=True)
                if not href or href.startswith("#") or "javascript:" in href:
                    continue
                full_url = urllib.parse.urljoin(url, href)
                
                # Filter out generic button text like 'ĐỌC NGAY', 'ĐỌC TỪ ĐẦU'
                is_generic_button = re.match(r"^(đọc ngay|đọc từ đầu|bắt đầu đọc|read now|first chapter)$", title.lower())
                
                # Check if we already have this URL
                existing_item = next((item for item in items if item.url == full_url), None)
                if existing_item:
                    # If existing had generic title and this one is better, update title
                    if re.match(r"^(đọc ngay|đọc từ đầu|bắt đầu đọc|read now)$", existing_item.title.lower()):
                        if not is_generic_button:
                            existing_item.title = title
                    continue
                
                if is_generic_button:
                    continue

                if full_url not in seen_urls and title:
                    seen_urls.add(full_url)
                    items.append(ChapterItem(index=len(seen_urls), title=title, url=full_url))

            return items

        # Harvest initial page
        chapters.extend(_harvest_links(soup))

        # If pagination exists on the story page, attempt to follow it
        if fetcher and chapters:
            pagination = soup.select(".pagination a, ul.pagination a, .page-item a, .nav-links a")
            visited_pages = {url}
            for pa in pagination:
                href = pa.get("href")
                if not href or href.startswith("#") or "javascript:" in href:
                    continue
                full_p = urllib.parse.urljoin(url, href)
                if full_p not in visited_pages:
                    visited_pages.add(full_p)
                    try:
                        p_html = fetcher.fetch(full_p, referer=url)
                        p_soup = BeautifulSoup(p_html, "html.parser")
                        new_items = _harvest_links(p_soup)
                        chapters.extend(new_items)
                    except Exception:
                        pass

        # Sort or preserve natural order
        for i, chap in enumerate(chapters, start=1):
            chap.index = i

        return chapters

    def extract_chapter_content(self, html: str, url: str, cleaner: Any) -> ChapterContent:
        soup = BeautifulSoup(html, "html.parser")

        # 1. Chapter Title
        title = ""
        title_candidates = soup.select(
            ".chapter-title, h1.chapter-title, h2.chapter-title, "
            ".title-chap, .title-chapter, h1, h2"
        )
        for t in title_candidates:
            txt = t.get_text(strip=True)
            if re.search(r"(chương|hồi|chap|chapter|tiết)", txt, re.I):
                title = txt
                break
        if not title and title_candidates:
            title = title_candidates[0].get_text(strip=True)
        if not title:
            title = "Chương không tiêu đề"

        # 2. Content Extraction with text density heuristics
        # Standard selectors first
        content_div = soup.select_one(
            "#chapter-c, .chapter-c, #chapter-content, .chapter-content, "
            "#content, .content, .entry-content, .post-content, "
            ".reading-content, #bookContentBody, article"
        )

        paragraphs = []
        if content_div:
            paragraphs = cleaner.clean_container(content_div)

        # If standard selectors yielded too few paragraphs, use text-density heuristic
        if len(paragraphs) < 3:
            best_element = None
            max_score = 0
            for el in soup.find_all(["div", "article", "section"]):
                # Avoid site wrappers with many nested sub-blocks
                sub_divs = len(el.find_all(["div", "section"]))
                if sub_divs > 6:
                    continue

                text = el.get_text(strip=True)
                text_len = len(text)
                if text_len > 400 and text_len > max_score:
                    max_score = text_len
                    best_element = el

            if best_element:
                heuristic_paras = cleaner.clean_container(best_element)
                if len(heuristic_paras) > len(paragraphs):
                    paragraphs = heuristic_paras

        # 3. Next Chapter link detection
        next_url = None
        # Priority selectors
        next_tag = soup.select_one(
            "#next_chap, a.next-chap, a.btn-next, a[rel='next'], "
            ".nav-next a, a.btn-chapter-nav"
        )
        if next_tag and next_tag.get("href"):
            raw_href = next_tag["href"]
            if not raw_href.startswith("#") and "javascript:" not in raw_href:
                next_url = urllib.parse.urljoin(url, raw_href)

        # Fallback: scan all <a> tags with keywords
        if not next_url:
            for a in soup.find_all("a", href=True):
                txt = a.get_text(strip=True).lower()
                if txt in ["chương tiếp", "chương sau", "tiếp theo", "next chapter", "next", "sau >"]:
                    raw_href = a["href"]
                    if not raw_href.startswith("#") and "javascript:" not in raw_href:
                        next_url = urllib.parse.urljoin(url, raw_href)
                        break

        return ChapterContent(
            title=title,
            url=url,
            paragraphs=paragraphs,
            next_url=next_url
        )

