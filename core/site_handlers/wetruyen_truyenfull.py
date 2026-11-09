"""
Dedicated Handler for TruyenFull, WeTruyen, DTruyen and compatible sites.
"""
import re
import urllib.parse
from typing import List, Optional, Any
from bs4 import BeautifulSoup
from .base import BaseSiteHandler, StoryInfo, ChapterItem, ChapterContent
from .universal import (
    extract_post_id,
    extract_slug_from_url,
    extract_chapter_date,
    extract_chapter_views,
    check_for_coming_soon,
    _is_pagination_link,
    extract_full_description
)

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
        check_for_coming_soon(soup)

        original_id = extract_post_id(soup, url)

        # Title
        title_tag = soup.select_one("h1.title, h3.title, .story-title, h1")
        title = title_tag.get_text(strip=True) if title_tag else "Truyện Chưa Đặt Tên"

        # Author
        author_tag = soup.select_one('a[itemprop="author"], .author a, .author')
        author = author_tag.get_text(strip=True) if author_tag else "Không rõ"

        # Description (preserve multi-paragraph formatting separated by \r\n\r\n)
        desc = extract_full_description(soup)

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
            original_id=original_id,
            slug=extract_slug_from_url(url, title),
            author=author,
            description=desc,
            cover_url=cover_url
        )

    def extract_chapter_list(self, html: str, url: str, fetcher: Any = None) -> List[ChapterItem]:
        soup = BeautifulSoup(html, "html.parser")
        check_for_coming_soon(soup)

        chapters: List[ChapterItem] = []
        seen_urls = set()

        def _discover_pagination(curr_soup: BeautifulSoup) -> tuple[int, Optional[str]]:
            pagination = curr_soup.select(
                "a.page-numbers, .chapter-pagination a, .es-pagination a, "
                ".pagination a, ul.pagination a, .page-item a, .wp-pagenavi a"
            )
            max_p = 1
            pattern = None
            for a in pagination:
                href = a.get("href")
                if not href or href.startswith("#") or "javascript:" in href:
                    continue
                full_href = urllib.parse.urljoin(url, href)
                m = re.search(r"(/(?:trang|page)[-/])(\d+)(/?(?:#.*)?)$", full_href, re.I)
                if m:
                    p_num = int(m.group(2))
                    if p_num > max_p:
                        max_p = p_num
                        pattern = re.sub(r"(/(?:trang|page)[-/])\d+(/?(?:#.*)?)$", r"\g<1>{PAGE}\g<2>", full_href, flags=re.I)
                else:
                    m2 = re.search(r"([?&](?:chap_page|page|trang|paged)=)(\d+)", full_href, re.I)
                    if m2:
                        p_num = int(m2.group(2))
                        if p_num > max_p:
                            max_p = p_num
                            pattern = re.sub(r"([?&](?:chap_page|page|trang|paged)=)\d+", r"\g<1>{PAGE}", full_href, flags=re.I)
            return max_p, pattern

        def _get_page_chaps(page_soup: BeautifulSoup) -> List[ChapterItem]:
            items = []
            links = page_soup.select(
                "#list-chapter a, .list-chapter a, .chapter-list a, "
                "ul.list-chapters a, .table-list a, .list-chap a"
            )
            if not links:
                links = [a for a in page_soup.find_all("a", href=True) if re.search(r"/(chuong|chapter)-\d+", a["href"])]

            for a in links:
                href = a.get("href", "")
                if not href or href.startswith("#") or "javascript:" in href:
                    continue
                if _is_pagination_link(a, href):
                    continue
                chap_url = urllib.parse.urljoin(url, href)
                chap_title = a.get_text(strip=True)
                if chap_url and chap_url not in seen_urls and chap_title:
                    seen_urls.add(chap_url)
                    items.append(ChapterItem(
                        index=len(seen_urls),
                        title=chap_title,
                        url=chap_url,
                        slug=extract_slug_from_url(chap_url, chap_title)
                    ))
            return items

        chapters.extend(_get_page_chaps(soup))
        max_page, page_pattern = _discover_pagination(soup)

        if fetcher and max_page > 1 and page_pattern:
            current_p = 2
            while current_p <= max_page:
                p_url = page_pattern.replace("{PAGE}", str(current_p))
                try:
                    p_html = fetcher.fetch(p_url, referer=url)
                    p_soup = BeautifulSoup(p_html, "html.parser")
                    new_chaps = _get_page_chaps(p_soup)
                    if not new_chaps:
                        break
                    chapters.extend(new_chaps)
                    sub_max, _ = _discover_pagination(p_soup)
                    if sub_max > max_page:
                        max_page = sub_max
                except Exception:
                    break
                current_p += 1

        for i, chap in enumerate(chapters, start=1):
            chap.index = i

        return chapters

    def extract_chapter_content(self, html: str, url: str, cleaner: Any) -> ChapterContent:
        soup = BeautifulSoup(html, "html.parser")
        check_for_coming_soon(soup)

        original_id = extract_post_id(soup, url)
        chap_date = extract_chapter_date(soup)
        chap_views = extract_chapter_views(soup)

        title_tag = soup.select_one(".chapter-title, h1.chapter-title, h2.chapter-title, .title-chap, h1")
        title = title_tag.get_text(strip=True) if title_tag else "Chương không tiêu đề"

        content_div = soup.select_one("#chapter-c, .chapter-c, #chapter-content, .chapter-content, .entry-content")

        paragraphs = []
        html_content = ""
        if content_div:
            paragraphs, html_content = cleaner.clean_container_to_html(content_div)
        else:
            best_div = None
            max_len = 0
            for div in soup.find_all(["div", "article"]):
                text_len = len(div.get_text(strip=True))
                if text_len > max_len and len(div.find_all("div")) < 5:
                    max_len = text_len
                    best_div = div
            if best_div:
                paragraphs, html_content = cleaner.clean_container_to_html(best_div)

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
            html_content=html_content,
            original_id=original_id,
            slug=extract_slug_from_url(url, title),
            date=chap_date,
            views=chap_views,
            next_url=next_url
        )
