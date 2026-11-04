"""
Dedicated Handler for TruyenFull, WeTruyen, DTruyen and compatible sites.
"""
import re
import urllib.parse
from typing import List, Optional, Any
from bs4 import BeautifulSoup
from .base import BaseSiteHandler, StoryInfo, ChapterItem, ChapterContent

class TruyenFullFamilyHandler(BaseSiteHandler):
    name = "TruyenFull / WeTruyen / DTruyen"

    def match(self, url: str) -> bool:
        domain = urllib.parse.urlparse(url).netloc.lower()
        matched = any(k in domain for k in [
            "truyenfull", "wetruyen", "dtruyen", "sstruyen",
            "thichtruyenchu", "truyenchu", "santruyen"
        ])
        return matched

    def extract_story_info(self, html: str, url: str) -> StoryInfo:
        soup = BeautifulSoup(html, "html.parser")

        # Title
        title_tag = soup.select_one("h1.title, h3.title, .story-title, h1")
        title = title_tag.get_text(strip=True) if title_tag else "Truyện Chưa Đặt Tên"

        # Author
        author_tag = soup.select_one('a[itemprop="author"], .author a, .author')
        author = author_tag.get_text(strip=True) if author_tag else "Không rõ"

        # Description
        desc_tag = soup.select_one(".desc-text, .story-desc, .content-desc, .desc")
        desc = desc_tag.get_text(strip=True) if desc_tag else ""

        # Cover
        cover_tag = soup.select_one(".books img, .book img, .thumb img, .story-info img")
        cover_url = ""
        if cover_tag:
            cover_url = cover_tag.get("src") or cover_tag.get("data-src", "")
            if cover_url:
                cover_url = urllib.parse.urljoin(url, cover_url)

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
        seen_urls = set()

        # Find total pages from pagination if present
        page_urls = [url]
        pagination = soup.select(".pagination a, ul.pagination a, .page-item a")
        max_page = 1
        page_pattern = None

        for a in pagination:
            href = a.get("href")
            if not href or href.startswith("#") or "javascript:" in href:
                continue
            full_href = urllib.parse.urljoin(url, href)
            # detect page pattern e.g. /trang-2/ or ?page=2
            m = re.search(r"trang-(\d+)", full_href)
            if m:
                p_num = int(m.group(1))
                if p_num > max_page:
                    max_page = p_num
                    page_pattern = full_href.replace(f"trang-{p_num}", "trang-{PAGE}")
            else:
                m2 = re.search(r"[?&]page=(\d+)", full_href)
                if m2:
                    p_num = int(m2.group(1))
                    if p_num > max_page:
                        max_page = p_num
                        page_pattern = re.sub(r"page=\d+", "page={PAGE}", full_href)

        # Helper to extract chapters from a single page soup
        def _get_page_chaps(page_soup: BeautifulSoup) -> List[ChapterItem]:
            items = []
            links = page_soup.select(
                "#list-chapter a, .list-chapter a, .chapter-list a, "
                "ul.list-chapters a, .table-list a, .list-chap a"
            )
            if not links:
                # Fallback: scan all links containing /chuong- or /chapter-
                links = [a for a in page_soup.find_all("a", href=True) if re.search(r"/(chuong|chapter)-\d+", a["href"])]

            for a in links:
                chap_url = urllib.parse.urljoin(url, a.get("href", ""))
                chap_title = a.get_text(strip=True)
                if chap_url and chap_url not in seen_urls and chap_title:
                    seen_urls.add(chap_url)
                    items.append(ChapterItem(index=len(seen_urls), title=chap_title, url=chap_url))
            return items

        # Page 1
        chapters.extend(_get_page_chaps(soup))

        # If there are additional pages and fetcher is provided, fetch remaining pages
        if fetcher and max_page > 1 and page_pattern:
            for p in range(2, max_page + 1):
                p_url = page_pattern.replace("{PAGE}", str(p))
                try:
                    p_html = fetcher.fetch(p_url, referer=url)
                    p_soup = BeautifulSoup(p_html, "html.parser")
                    new_chaps = _get_page_chaps(p_soup)
                    if not new_chaps:
                        break
                    chapters.extend(new_chaps)
                except Exception as e:
                    # Log or break if page failed
                    break

        # Re-index chapters sequentially
        for i, chap in enumerate(chapters, start=1):
            chap.index = i

        return chapters

    def extract_chapter_content(self, html: str, url: str, cleaner: Any) -> ChapterContent:
        soup = BeautifulSoup(html, "html.parser")

        # Chapter Title
        title_tag = soup.select_one(".chapter-title, h1.chapter-title, h2.chapter-title, .title-chap, h1")
        title = title_tag.get_text(strip=True) if title_tag else "Chương không tiêu đề"

        # Content container
        content_div = soup.select_one("#chapter-c, .chapter-c, #chapter-content, .chapter-content, .entry-content")

        paragraphs = []
        if content_div:
            paragraphs = cleaner.clean_container(content_div)
        else:
            # Fallback heuristic: find container with maximum paragraph text
            best_div = None
            max_len = 0
            for div in soup.find_all(["div", "article"]):
                text_len = len(div.get_text(strip=True))
                # Skip if too many sub-divs (likely layout wrapper)
                if text_len > max_len and len(div.find_all("div")) < 5:
                    max_len = text_len
                    best_div = div
            if best_div:
                paragraphs = cleaner.clean_container(best_div)

        # Next chapter link
        next_tag = soup.select_one(
            "#next_chap, a.next-chap, a.btn-next, a[rel='next'], "
            "a:-soup-contains('Chương tiếp'), a:-soup-contains('Tiếp theo')"
        )
        next_url = None
        if next_tag and next_tag.get("href"):
            raw_href = next_tag["href"]
            if not raw_href.startswith("#") and "javascript:" not in raw_href:
                next_url = urllib.parse.urljoin(url, raw_href)

        return ChapterContent(
            title=title,
            url=url,
            paragraphs=paragraphs,
            next_url=next_url
        )
