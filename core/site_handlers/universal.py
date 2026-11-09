"""
Universal Adaptive Site Handler.
Automatically detects and extracts novel information, chapter lists, and content from any website.
"""
import re
import zlib
import unicodedata
import urllib.parse
from datetime import datetime
from typing import List, Optional, Any, Set
from bs4 import BeautifulSoup, Tag
from .base import BaseSiteHandler, StoryInfo, ChapterItem, ChapterContent

def slugify_vi(text: str) -> str:
    """Convert Vietnamese string into a clean URL slug."""
    text = text.lower()
    text = re.sub(r"[đĐ]", "d", text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "chuong"

def extract_slug_from_url(url: str, fallback_title: str = "") -> str:
    """Extract clean slug from URL path or fallback to slugified title."""
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.rstrip("/")
    if path:
        last_seg = path.split("/")[-1]
        last_seg = re.sub(r"\.(html|htm|php|asp|aspx)$", "", last_seg, flags=re.I)
        last_seg = re.sub(r"\.\d+$", "", last_seg)
        if last_seg and not last_seg.isdigit():
            return last_seg.lower()
    return slugify_vi(fallback_title)

def extract_post_id(soup: BeautifulSoup, url: str) -> int:
    """Extract WordPress post ID or numeric story/chapter ID from HTML or URL."""
    # 1. Check body class for postid-XXXX
    if soup.body and soup.body.get("class"):
        classes = " ".join(soup.body.get("class", []))
        m = re.search(r"\bpostid-(\d+)\b", classes)
        if m:
            return int(m.group(1))

    # 2. Check data-story-id on .es-chapters
    es_chaps = soup.select_one("[data-story-id]")
    if es_chaps and str(es_chaps.get("data-story-id", "")).isdigit():
        return int(es_chaps["data-story-id"])

    # 3. Check shortlink <link rel="shortlink" href="...?p=15789">
    shortlink = soup.find("link", rel="shortlink")
    if shortlink and shortlink.get("href"):
        m = re.search(r"[?&]p=(\d+)", shortlink["href"])
        if m:
            return int(m.group(1))

    # 4. Check article id="post-XXXX"
    article = soup.find("article", id=re.compile(r"^post-\d+$"))
    if article:
        m = re.search(r"(\d+)", article["id"])
        if m:
            return int(m.group(1))

    # 5. Check URL for numeric ID e.g. /truyen/1600/ or .1381/
    m_url = re.search(r"/(?:truyen|story|book)/(\d+)(?:/|$)", url)
    if m_url:
        return int(m_url.group(1))
    m_dot = re.search(r"\.(\d+)/?$", url)
    if m_dot:
        return int(m_dot.group(1))

    # 6. Deterministic hash fallback
    return zlib.crc32(url.encode("utf-8")) % 900000 + 10000

def extract_chapter_date(soup: BeautifulSoup) -> str:
    """Extract chapter publication date in 'YYYY-MM-DD HH:MM:SS' format."""
    meta_date = soup.select_one('meta[property="article:published_time"], meta[property="og:updated_time"], time[datetime]')
    if meta_date:
        raw_dt = meta_date.get("content") or meta_date.get("datetime", "")
        m = re.search(r"(\d{4}-\d{2}-\d{2})[T\s](\d{2}:\d{2}:\d{2})", raw_dt)
        if m:
            return f"{m.group(1)} {m.group(2)}"

    date_el = soup.select_one(".item-date .item__value, .chapter-date, .post-date")
    if date_el:
        txt = date_el.get_text(strip=True)
        m = re.search(r"(\d{2})[-/](\d{2})[-/](\d{4})", txt)
        if m:
            now_time = datetime.now().strftime("%H:%M:%S")
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)} {now_time}"

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def extract_chapter_views(soup: BeautifulSoup) -> Optional[int]:
    """Extract chapter view count if displayed on page."""
    view_el = soup.select_one(".item-view .item__value")
    if view_el:
        txt = re.sub(r"[^\d]", "", view_el.get_text(strip=True))
        if txt.isdigit():
            return int(txt)
    return None

def check_for_coming_soon(soup: BeautifulSoup):
    """Raise a clear error if the target WordPress site has Hostinger Coming Soon / Maintenance mode active."""
    title_txt = soup.title.get_text(strip=True) if soup.title else ""
    if title_txt.lower() == "coming soon" or soup.select_one(".hsr-coming-soon-body"):
        raise ValueError(
            "Website nguồn đang bật chế độ bảo trì 'Coming Soon' (Hostinger), hiện chưa mở công khai nội dung truyện."
        )

def _is_pagination_link(a_tag: Tag, href: str) -> bool:
    """Return True if an <a> tag is a pagination link rather than a chapter link."""
    a_classes = " ".join(a_tag.get("class", [])).lower()
    if any(c in a_classes for c in ["page-numbers", "page-link", "pagenavi"]):
        return True

    # Check if inside a pagination container
    for parent in a_tag.parents:
        if isinstance(parent, Tag):
            p_classes = " ".join(parent.get("class", [])).lower()
            p_id = (parent.get("id") or "").lower()
            if any(k in p_classes or k in p_id for k in ["pagination", "pagenavi", "page-numbers", "nav-links", "pager"]):
                return True

    # Check href query/path patterns for pagination
    if re.search(r"[?&](?:chap_page|page|trang|paged)=\d+", href, re.I):
        return True
    if re.search(r"/(?:trang|page)[-/]\d+/?(?:#.*)?$", href, re.I):
        return True

    return False

def extract_full_description(soup: BeautifulSoup) -> str:
    """
    Extract the complete story synopsis ('văn án') directly from the story page HTML.
    Supports standard novel themes (.group-box .content, #text-box, .summary-content, .desc-text, etc.),
    Flatsome/Elementor column layouts (.col-inner, .elementor-widget-text-editor), and parent container
    resolution anchored by meta og:description so truncated meta tags are expanded to the full on-page text.
    """
    ui_noise_regex = re.compile(
        r"^(xem thêm|thu gọn|đọc tiếp|đọc từ đầu|đọc tập mới|đọc ngay|mục lục|danh sách chương|"
        r"rate this post|\d+(\.\d+)?/\d+\s*-\s*\(\d+\s*bình chọn\)|\.{2,}|…+)$",
        re.I
    )

    # Read meta og:description / description first (used both as anchor and last-resort fallback)
    meta_desc = ""
    for meta in soup.select('meta[property="og:description"], meta[name="description"]'):
        c = (meta.get("content") or "").replace("\xa0", " ").strip()
        if c and not ui_noise_regex.match(c) and len(c) > len(meta_desc):
            meta_desc = c

    meta_prefix_norm = re.sub(r"[^\w]", "", meta_desc.lower())[:35] if len(meta_desc) >= 20 else ""

    def _clean_container_to_desc(dc: Tag, direct_p_only: bool = False) -> str:
        dc_copy = BeautifulSoup(str(dc), "html.parser")
        root = dc_copy.find() or dc_copy

        # Remove non-description elements inside container
        for noise in root.select(
            "script, style, ins, iframe, button, h1, h2, h3, h4, ul, ol, table, form, "
            ".kk-star-ratings, .kksr-stars, .kksr-legend, .info, .box-text, .wpdiscuz, #comments, "
            ".summary-overlay, .btn-toggle-modern, .es-story-actions, .es-chapters, "
            ".chapter-list, #list-chapter, #danh-sach-chuong, .list-chapter, .chapter-pagination, "
            ".code-block, [class*='ai-viewport'], [class*='ai-insert'], .er-partner-info, "
            "[data-affiliate-click], a.es-btn, #story-style-form"
        ):
            noise.decompose()

        # Unwrap anti-copy <span class="fake" data-before="..."> tags
        for sp in root.select("span.fake, span[data-before], span[data-after]"):
            before_txt = sp.get("data-before", "")
            after_txt = sp.get("data-after", "")
            if not sp.get_text().strip() and (before_txt or after_txt):
                sp.string = f"{before_txt}{after_txt}"
            sp.unwrap()

        for br in root.find_all("br"):
            br.replace_with("\n")

        paras: List[str] = []
        p_tags = root.find_all("p", recursive=False) if direct_p_only else root.find_all("p")
        if p_tags:
            for p in p_tags:
                raw_p = p.get_text().replace("\xa0", " ")
                for line in raw_p.splitlines():
                    clean_line = re.sub(r"[ \t]+", " ", line).strip()
                    if clean_line and not ui_noise_regex.match(clean_line):
                        paras.append(clean_line)
        elif not direct_p_only:
            raw_txt = root.get_text("\n").replace("\xa0", " ")
            for line in raw_txt.splitlines():
                clean_line = re.sub(r"[ \t]+", " ", line).strip()
                if clean_line and not ui_noise_regex.match(clean_line):
                    paras.append(clean_line)

        return "\r\n\r\n".join(paras)

    best_desc = ""
    best_len = 0

    # 1. Check dedicated synopsis containers
    desc_selectors = (
        ".group-box .content, #text-box.summary-content, #text-box, .summary-content, "
        ".desc-text, .story-desc, .content-desc, .book-intro, .novel-desc, "
        ".story-introduction, .van-an, #van-an, .gioi-thieu, #gioi-thieu, "
        '[itemprop="description"], .box-description, .tab-summary, '
        ".description, .desc, .summary, .intro, #description, .entry-content, .post-content"
    )
    for dc in soup.select(desc_selectors):
        candidate = _clean_container_to_desc(dc, direct_p_only=False)
        cand_len = len(candidate)
        if cand_len >= 25 and cand_len > best_len:
            best_len = cand_len
            best_desc = candidate

    # 2. Check Flatsome / Elementor / generic containers (e.g. .col-inner on comong.info)
    # Especially when meta og:description is present and matches a paragraph inside that container,
    # or when a .col-inner has multiple direct <p> children forming the story description.
    for col in soup.select(".col-inner, .elementor-widget-text-editor, .wpb_wrapper"):
        if col.find_parent(class_=re.compile(r"(footer|header|comment|widget|sidebar|box-text)", re.I)):
            continue
        direct_ps = col.find_all("p", recursive=False)
        if len(direct_ps) >= 2:
            candidate = _clean_container_to_desc(col, direct_p_only=True)
            cand_len = len(candidate)
            if cand_len >= 50:
                cand_norm = re.sub(r"[^\w]", "", candidate.lower())
                # Prioritize if it matches og:description prefix or if no dedicated container was found
                if (meta_prefix_norm and meta_prefix_norm in cand_norm) or best_len == 0:
                    if cand_len > best_len:
                        best_len = cand_len
                        best_desc = candidate

    # 3. Anchor search from meta og:description if best_desc is still shorter than or equal to meta_desc
    if meta_prefix_norm and best_len <= len(meta_desc) + 20:
        for p_tag in soup.find_all("p"):
            p_norm = re.sub(r"[^\w]", "", p_tag.get_text().lower())
            if meta_prefix_norm in p_norm and p_tag.parent:
                candidate = _clean_container_to_desc(p_tag.parent, direct_p_only=False)
                if len(candidate) > best_len:
                    best_len = len(candidate)
                    best_desc = candidate

    # 4. Fallback to meta og:description if nothing longer was found in the DOM
    if len(meta_desc) > best_len:
        paras = [re.sub(r"[ \t]+", " ", l).strip() for l in meta_desc.splitlines() if l.strip()]
        best_desc = "\r\n\r\n".join(paras)

    return best_desc

class UniversalSiteHandler(BaseSiteHandler):
    name = "Universal Auto-Detector"

    def match(self, url: str) -> bool:
        return True

    def extract_story_info(self, html: str, url: str) -> StoryInfo:
        soup = BeautifulSoup(html, "html.parser")
        check_for_coming_soon(soup)

        original_id = extract_post_id(soup, url)

        # 1. Title Extraction
        title = ""
        h1 = soup.select_one("h1.title, h1.story-title, h1.entry-title, h1")
        if h1:
            title = h1.get_text(strip=True)

        if not title:
            og_title = soup.select_one('meta[property="og:title"]')
            if og_title and og_title.get("content"):
                title = og_title["content"].strip()

        if not title and soup.title:
            title = soup.title.get_text(strip=True)

        title = re.sub(
            r"\s*[-|–]\s*(Đọc truyện|Truyện Full|Online|Tàng Thư Viện|Wattpad|WeTruyen|TruyenFull|[a-zA-Z0-9.\-]+\.(com|vn|net|org)).*$",
            "",
            title,
            flags=re.IGNORECASE
        ).strip()
        title = re.sub(r"^(#ST\d+)\s*[–—-]\s*", r"\1 - ", title)
        if not title:
            title = "Truyện Không Tên"

        # 2. Author Extraction
        author = "Không rõ"
        author_meta = soup.select_one('meta[name="author"], [itemprop="author"], .author a, .author')
        if author_meta:
            author = author_meta.get("content") or author_meta.get_text(strip=True)
        else:
            m = re.search(r"Tác giả\s*:\s*([^<\n\r,]+)", html, re.IGNORECASE)
            if m:
                author = m.group(1).strip()

        author = re.sub(r"<[^>]+>", "", author).strip() or "Không rõ"

        # 3. Description Extraction
        desc = extract_full_description(soup)

        # 4. Cover URL
        cover_url = ""
        og_img = soup.select_one('meta[property="og:image"]')
        if og_img and og_img.get("content"):
            cover_url = urllib.parse.urljoin(url, og_img["content"].strip())

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
        seen_urls: Set[str] = set()

        def _extract_link_title_and_date(a_tag: Tag) -> tuple[str, str]:
            title_span = a_tag.select_one(".chapter-title, .chap-title, .chap-no")
            date_span = a_tag.select_one(".chapter-date, .chap-date")
            chap_date = ""
            if date_span:
                d_txt = date_span.get_text(strip=True)
                m = re.search(r"(\d{2})[-/](\d{2})[-/](\d{4})", d_txt)
                if m:
                    chap_date = f"{m.group(3)}-{m.group(2)}-{m.group(1)} {datetime.now().strftime('%H:%M:%S')}"

            if title_span:
                return title_span.get_text(strip=True), chap_date

            if date_span:
                clone = BeautifulSoup(str(a_tag), "html.parser")
                for ds in clone.select(".chapter-date, .chap-date"):
                    ds.decompose()
                return clone.get_text(strip=True), chap_date

            return a_tag.get_text(strip=True), chap_date

        def _harvest_links(curr_soup: BeautifulSoup) -> List[ChapterItem]:
            items = []
            # Priority 1: inner chapter list containers (avoid outer wrappers that include pagination)
            containers = curr_soup.select(
                ".chapter-list, #danh-sach-chuong, #list-chapter, .list-chapter, "
                ".list-chapters, .chapters, #chapters, .table-list, ul.list-chap, .box-chap"
            )
            candidate_links = []
            if containers:
                for c in containers:
                    candidate_links.extend(c.find_all("a", href=True))
            else:
                for a in curr_soup.find_all("a", href=True):
                    href = a.get("href", "")
                    text = a.get_text(strip=True)
                    if href.startswith("#") or "javascript:" in href or href == "/":
                        continue
                    if _is_pagination_link(a, href):
                        continue
                    a_classes = " ".join(a.get("class", []))
                    if any(btn_cls in a_classes for btn_cls in ["es-btn", "btn-primary", "btn-secondary", "btn-success"]):
                        continue
                    if re.search(r"(chuong|chapter|chap|hoi)[-_/]?\d+", href, re.I) or re.search(r"^(Chương|Hồi|Chap|Chapter)\s+\d+", text, re.I):
                        candidate_links.append(a)

            for a in candidate_links:
                href = a.get("href", "")
                if not href or href.startswith("#") or "javascript:" in href:
                    continue

                if _is_pagination_link(a, href):
                    continue

                a_classes = " ".join(a.get("class", []))
                if any(btn_cls in a_classes for btn_cls in ["es-btn", "btn-primary", "btn-secondary", "btn-success"]):
                    continue

                title, chap_date = _extract_link_title_and_date(a)
                full_url = urllib.parse.urljoin(url, href)

                is_generic_button = bool(re.match(
                    r"^(đọc ngay|đọc từ đầu|đọc tập mới|đọc mới nhất|bắt đầu đọc|mục lục|read now|first chapter|\d+)$",
                    title.lower().strip()
                ))

                existing_item = next((item for item in items if item.url == full_url), None)
                if existing_item:
                    if re.match(r"^(đọc ngay|đọc từ đầu|đọc tập mới|đọc mới nhất|bắt đầu đọc|read now)$", existing_item.title.lower()):
                        if not is_generic_button and title:
                            existing_item.title = title
                    continue

                if is_generic_button:
                    continue

                if full_url not in seen_urls and title:
                    seen_urls.add(full_url)
                    items.append(ChapterItem(
                        index=len(seen_urls),
                        title=title,
                        url=full_url,
                        slug=extract_slug_from_url(full_url, title),
                        date=chap_date
                    ))

            return items

        def _discover_pagination(curr_soup: BeautifulSoup) -> tuple[int, Optional[str], List[str]]:
            """
            Scan a page soup for chapter pagination links.
            Returns (max_page, page_pattern_with_{PAGE}, explicit_page_urls).
            """
            pag_links = curr_soup.select(
                "a.page-numbers, .chapter-pagination a, .es-pagination a, "
                ".pagination a, ul.pagination a, .page-item a, .nav-links a, .wp-pagenavi a"
            )
            max_p = 1
            pattern = None
            explicit_urls = []

            for pa in pag_links:
                href = pa.get("href", "")
                if not href or href.startswith("#") or "javascript:" in href:
                    continue
                full_p = urllib.parse.urljoin(url, href)
                if full_p not in explicit_urls:
                    explicit_urls.append(full_p)

                # Pattern 1: ?chap_page=2 or ?page=2 or ?trang=2 or ?paged=2
                m_query = re.search(r"([?&](?:chap_page|page|trang|paged)=)(\d+)", full_p, re.I)
                if m_query:
                    p_num = int(m_query.group(2))
                    if p_num > max_p:
                        max_p = p_num
                        pattern = re.sub(r"([?&](?:chap_page|page|trang|paged)=)\d+", r"\g<1>{PAGE}", full_p, flags=re.I)
                    continue

                # Pattern 2: /trang-2/ or /page/2/ or /page-2/
                m_path = re.search(r"(/(?:trang|page)[-/])(\d+)(/?(?:#.*)?)$", full_p, re.I)
                if m_path:
                    p_num = int(m_path.group(2))
                    if p_num > max_p:
                        max_p = p_num
                        pattern = re.sub(r"(/(?:trang|page)[-/])\d+(/?(?:#.*)?)$", r"\g<1>{PAGE}\g<2>", full_p, flags=re.I)

            return max_p, pattern, explicit_urls

        # Harvest page 1
        chapters.extend(_harvest_links(soup))

        # Follow all pagination pages sequentially
        if fetcher and chapters:
            max_page, page_pattern, explicit_urls = _discover_pagination(soup)
            visited_pages = {url}

            if max_page > 1 and page_pattern:
                current_p = 2
                while current_p <= max_page:
                    p_url = page_pattern.replace("{PAGE}", str(current_p))
                    if p_url not in visited_pages:
                        visited_pages.add(p_url)
                        try:
                            p_html = fetcher.fetch(p_url, referer=url)
                            p_soup = BeautifulSoup(p_html, "html.parser")
                            new_items = _harvest_links(p_soup)
                            if not new_items:
                                break
                            chapters.extend(new_items)
                            # Dynamically check if this page reveals even higher page numbers (e.g. beyond ellipsis '...')
                            sub_max, _, _ = _discover_pagination(p_soup)
                            if sub_max > max_page:
                                max_page = sub_max
                        except Exception:
                            break
                    current_p += 1
            elif explicit_urls:
                for full_p in explicit_urls:
                    if full_p not in visited_pages:
                        visited_pages.add(full_p)
                        try:
                            p_html = fetcher.fetch(full_p, referer=url)
                            p_soup = BeautifulSoup(p_html, "html.parser")
                            new_items = _harvest_links(p_soup)
                            chapters.extend(new_items)
                        except Exception:
                            pass

        for i, chap in enumerate(chapters, start=1):
            chap.index = i

        return chapters

    def extract_chapter_content(self, html: str, url: str, cleaner: Any) -> ChapterContent:
        soup = BeautifulSoup(html, "html.parser")
        check_for_coming_soon(soup)

        original_id = extract_post_id(soup, url)
        chap_date = extract_chapter_date(soup)
        chap_views = extract_chapter_views(soup)

        # 1. Chapter Title
        title = ""
        title_candidates = soup.select(
            "h1.title, .chapter-title, h1.chapter-title, h2.chapter-title, "
            ".title-chap, .title-chapter, h1, h2"
        )
        for t in title_candidates:
            txt = t.get_text(strip=True)
            if re.search(r"(chương|hồi|chap|chapter|tiết|#st\d+)", txt, re.I):
                title = txt
                break
        if not title and title_candidates:
            title = title_candidates[0].get_text(strip=True)
        if not title:
            title = "Chương không tiêu đề"

        # 2. Content Extraction
        content_div = soup.select_one(
            ".es-post .content, .content.es-fs-md, #chapter-c, .chapter-c, "
            "#chapter-content, .chapter-content, #content, .content, "
            ".entry-content, .post-content, .reading-content, #bookContentBody, article"
        )

        paragraphs: List[str] = []
        html_content: str = ""
        if content_div:
            paragraphs, html_content = cleaner.clean_container_to_html(content_div)

        if len(paragraphs) < 2:
            best_element = None
            max_score = 0
            for el in soup.find_all(["div", "article", "section"]):
                sub_divs = len(el.find_all(["div", "section"]))
                if sub_divs > 6:
                    continue
                text = el.get_text(strip=True)
                text_len = len(text)
                if text_len > 300 and text_len > max_score:
                    max_score = text_len
                    best_element = el

            if best_element:
                h_paras, h_html = cleaner.clean_container_to_html(best_element)
                if len(h_paras) > len(paragraphs):
                    paragraphs = h_paras
                    html_content = h_html

        # 3. Next Chapter link detection (must belong to the same domain)
        base_netloc = urllib.parse.urlparse(url).netloc.lower()
        next_url = None
        next_tag = soup.select_one(
            "#next_chap, a.next-chap, a.btn-next, a.es-btn.next, a[rel='next'], "
            ".nav-next a, a.btn-chapter-nav"
        )
        if next_tag and next_tag.get("href"):
            raw_href = next_tag["href"]
            if not raw_href.startswith("#") and "javascript:" not in raw_href and not _is_pagination_link(next_tag, raw_href):
                cand_url = urllib.parse.urljoin(url, raw_href)
                if urllib.parse.urlparse(cand_url).netloc.lower() == base_netloc and cand_url.rstrip("/") != url.rstrip("/"):
                    next_url = cand_url

        if not next_url:
            for a in soup.find_all("a", href=True):
                txt = a.get_text(strip=True).lower()
                if txt in ["chương tiếp", "chương sau", "tiếp theo", "next chapter", "next", "sau >"]:
                    raw_href = a["href"]
                    if not raw_href.startswith("#") and "javascript:" not in raw_href and not _is_pagination_link(a, raw_href):
                        cand_url = urllib.parse.urljoin(url, raw_href)
                        if urllib.parse.urlparse(cand_url).netloc.lower() == base_netloc and cand_url.rstrip("/") != url.rstrip("/"):
                            next_url = cand_url
                            break

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
