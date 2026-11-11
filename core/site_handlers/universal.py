"""
Universal Adaptive Site Handler.
Automatically detects and extracts novel information, chapter lists, and content from any website.
"""
import re
import zlib
import logging
import unicodedata
import urllib.parse
from datetime import datetime
from typing import List, Optional, Any, Set, Tuple
from bs4 import BeautifulSoup, Tag
from .base import BaseSiteHandler, StoryInfo, ChapterItem, ChapterContent

logger = logging.getLogger("UniversalHandler")

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


def _extract_chap_num(item: ChapterItem) -> Optional[float]:
    """Extract numeric chapter index from chapter title or URL for ordering verification."""
    m_title = re.search(r"(?:chương|chap|chapter|hồi|tiết|phần)\s*(\d+(?:\.\d+)?)", item.title, re.I)
    if m_title:
        try:
            return float(m_title.group(1))
        except ValueError:
            pass

    m_url = re.search(r"(?:chuong|chap|chapter|hoi)[-_/](\d+)(?:[-_.](\d+))?", item.url, re.I)
    if m_url:
        try:
            if m_url.group(2):
                return float(f"{m_url.group(1)}.{m_url.group(2)}")
            return float(m_url.group(1))
        except ValueError:
            pass
    return None


def _normalize_chapter_order(chapters: List[ChapterItem]) -> List[ChapterItem]:
    """
    Detect if a website lists chapters in reverse/descending order (e.g. Chương 22 -> Chương 1)
    or out-of-order across pages, and automatically sort them into ascending order (Chương 1 -> Chương N).
    """
    if len(chapters) < 2:
        return chapters

    nums = [_extract_chap_num(ch) for ch in chapters]
    valid_pairs = [(idx, n) for idx, n in enumerate(nums) if n is not None]

    if len(valid_pairs) >= 2 and len(valid_pairs) >= len(chapters) * 0.6:
        # Case 1: All chapters have distinct detected chapter numbers
        if len(valid_pairs) == len(chapters) and len(set(nums)) == len(chapters):
            if nums != sorted(nums):
                paired = sorted(zip(nums, range(len(chapters)), chapters), key=lambda x: (x[0], x[1]))
                chapters = [p[2] for p in paired]
        # Case 2: Chapters are listed newest-first (descending order)
        elif valid_pairs[0][1] > valid_pairs[-1][1]:
            chapters = list(reversed(chapters))

    for i, chap in enumerate(chapters, start=1):
        chap.index = i
    return chapters


def format_story_title_with_code(title: str, story_code: str) -> str:
    """
    Format story title by replacing any existing code prefix with the provided story_code.
    Example:
      title='#ST1148 - ĐÊM TRÚNG...', story_code='#ST12435'
      -> '#ST12435 - ĐÊM TRÚNG...'
    """
    if not story_code:
        return title
    clean_code = story_code.strip().rstrip("-–—: ").strip()
    if not clean_code:
        return title
    if not clean_code.startswith("#") and re.match(r"^[A-Za-z]{2,}\d+", clean_code):
        clean_code = f"#{clean_code}"
    clean_title = re.sub(
        r"^(?:#[A-Za-z0-9_-]+(?:\s*\d+)?|[A-Za-z]{2,6}\s*\d+)\s*[-–—:\s]*\s*",
        "",
        title,
        flags=re.IGNORECASE
    ).strip()
    if not clean_title:
        clean_title = title.strip()
    return f"{clean_code} - {clean_title}"


def format_chapter_title_with_code(chap_title: str, chap_num: int, story_code: str) -> str:
    """
    Insert story_code before the chapter term ('Chương X').
    Examples:
      #TTY1 Chương 1 -> #ST12435 - Chương 1
      Chương 1 -> #ST12435 - Chương 1
      #STT143 - Chương 1 -> #ST12435 - Chương 1
      Sáu giờ bốn mươi tối - Chương 22 -> #ST12435 - Chương 22
      Chương 1: Mở đầu -> #ST12435 - Chương 1: Mở đầu
    """
    if not story_code:
        return chap_title
    clean_code = story_code.strip().rstrip("-–—: ").strip()
    if not clean_code:
        return chap_title
    if not clean_code.startswith("#") and re.match(r"^[A-Za-z]{2,}\d+", clean_code):
        clean_code = f"#{clean_code}"

    m = re.search(r"\b(Chương|Chap|Chapter|Hồi)\s*(\d+(?:\.\d+)?)(.*)$", chap_title, re.IGNORECASE)
    if m:
        term = m.group(1).capitalize()
        if term.lower() in ("chap", "chapter"):
            term = "Chương"
        num_str = m.group(2)
        rest = m.group(3).strip()
        if rest:
            rest_m = re.match(r"^[:.\-–—\s]+(.*)$", rest)
            if rest_m and rest_m.group(1):
                sep = ": " if rest.startswith(":") else " - "
                return f"{clean_code} - {term} {num_str}{sep}{rest_m.group(1).strip()}"
        return f"{clean_code} - {term} {num_str}"

    m_num = re.match(r"^\s*(?:(?:#[A-Za-z0-9_-]+|[A-Za-z]{2,6}\s*\d+)\s*[-–—:]\s*)?(\d+)(.*)$", chap_title)
    if m_num:
        num_str = m_num.group(1)
        rest = m_num.group(2).strip()
        if rest:
            rest_m = re.match(r"^[:.\-–—\s]+(.*)$", rest)
            if rest_m and rest_m.group(1):
                sep = ": " if rest.startswith(":") else " - "
                return f"{clean_code} - Chương {num_str}{sep}{rest_m.group(1).strip()}"
        return f"{clean_code} - Chương {num_str}"

    if chap_num and chap_num > 0:
        return f"{clean_code} - Chương {chap_num}"

    return f"{clean_code} - {chap_title}"


def parse_url_and_code(raw_line: str, default_code: str = "") -> Tuple[str, str]:
    """
    Parse a line containing a novel URL and an optional story code.
    Supports formats:
      - https://site.com/truyen/1/ | #ST12435
      - https://site.com/truyen/1/ #ST12435
      - #ST12435 | https://site.com/truyen/1/
      - https://site.com/truyen/1/
    """
    raw_line = raw_line.strip()
    if not raw_line:
        return "", ""

    m = re.search(r"(https?://[^\s|,;\"'>]+)", raw_line)
    if not m:
        return "", ""

    url = m.group(1).strip()
    rest = (raw_line[:m.start()] + " " + raw_line[m.end():]).strip()
    code = re.sub(r"^[|\-–—,;: \t]+|[|\-–—,;: \t]+$", "", rest).strip()

    if not code:
        code = default_code.strip() if default_code else ""

    if code:
        code = code.rstrip("-–—: ").strip()
        if not code.startswith("#") and re.match(r"^[A-Za-z]{2,}\d+", code):
            code = f"#{code}"

    return url, code


def _is_same_or_mirror_domain(cand_url: str, base_url: str) -> bool:
    """
    Check if cand_url belongs to the same domain, a subdomain, or a known mirror domain
    (e.g., vivutruyen.net vs vivutruyen2.net, or URL sharing the story slug).
    """
    try:
        cand_parsed = urllib.parse.urlparse(cand_url)
        base_parsed = urllib.parse.urlparse(base_url)
        cand_netloc = cand_parsed.netloc.lower().split(":")[0]
        base_netloc = base_parsed.netloc.lower().split(":")[0]
        if not cand_netloc or not base_netloc:
            return False
        if cand_netloc == base_netloc:
            return True

        # Check domain parts (e.g. vivutruyen2.net vs vivutruyen.net)
        cand_parts = cand_netloc.split(".")
        base_parts = base_netloc.split(".")
        if len(cand_parts) >= 2 and len(base_parts) >= 2:
            cand_sld = cand_parts[-2]
            base_sld = base_parts[-2]
            cand_core = re.sub(r"\d+$", "", cand_sld)
            base_core = re.sub(r"\d+$", "", base_sld)
            if cand_core and base_core and (cand_core == base_core or cand_core in base_core or base_core in cand_core):
                return True

        # Check if cand_url contains the story slug from base_url
        base_path_parts = [p for p in base_parsed.path.split("/") if p]
        cand_path_parts = [p for p in cand_parsed.path.split("/") if p]
        for bp in base_path_parts:
            # Story slug is usually a hyphenated string with length >= 6 and not a standard directory like 'truyen' or 'manga'
            if len(bp) >= 6 and "-" in bp and bp in cand_path_parts:
                return True
    except Exception:
        pass
    return False


def _find_in_content_continuation_link(soup: BeautifulSoup, current_url: str, title: str = "") -> Optional[str]:
    """
    Find continuation link embedded in chapter content (e.g. 'CHƯƠNG 6 – ẤN ĐỂ ĐỌC TIẾP: <link>').
    Commonly used when sites split stories across mirror domains.
    """
    continuation_patterns = [
        r"ấn\s*để\s*đọc\s*tiếp",
        r"bấm\s*để\s*đọc\s*tiếp",
        r"click\s*để\s*đọc\s*tiếp",
        r"đọc\s*tiếp\s*(?:chương|tập|phần)?",
        r"xem\s*tiếp\s*(?:chương|tập|phần)?",
        r"link\s*đọc\s*tiếp",
        r"chương\s*\d+\s*[-–—:]+\s*ấn\s*để\s*đọc\s*tiếp",
        r"qua\s*(?:web|trang)\s*mới\s*đọc\s*tiếp",
    ]
    cont_regex = re.compile("|".join(continuation_patterns), re.IGNORECASE)

    containers = soup.select(
        "#chapter-content, .chapter-content, #chapter-c, .chapter-c, "
        ".reading, .reading-content, .entry-content, .post-content, "
        ".es-post .content, .content.es-fs-md, article, body"
    ) or [soup]

    for container in containers:
        for a in container.find_all("a", href=True):
            href = a.get("href", "").strip()
            if not href or href.startswith("#") or "javascript:" in href:
                continue
            a_text = a.get_text(separator=" ", strip=True)
            parent_text = a.parent.get_text(separator=" ", strip=True) if a.parent else ""
            if cont_regex.search(a_text) or cont_regex.search(parent_text):
                cand_url = urllib.parse.urljoin(current_url, href)
                if cand_url.rstrip("/") != current_url.rstrip("/"):
                    if _is_same_or_mirror_domain(cand_url, current_url):
                        return cand_url

        for p in container.find_all(["p", "div", "span"]):
            p_text = p.get_text(separator=" ", strip=True)
            if cont_regex.search(p_text):
                a_tag = p.find("a", href=True)
                if a_tag:
                    href = a_tag.get("href", "").strip()
                    if href and not href.startswith("#") and "javascript:" not in href:
                        cand_url = urllib.parse.urljoin(current_url, href)
                        if cand_url.rstrip("/") != current_url.rstrip("/") and _is_same_or_mirror_domain(cand_url, current_url):
                            return cand_url
                m_url = re.search(r"https?://[^\s<>\"'`]+", p_text)
                if m_url:
                    cand_url = m_url.group(0).rstrip(".,;)>]")
                    if cand_url.rstrip("/") != current_url.rstrip("/") and _is_same_or_mirror_domain(cand_url, current_url):
                        return cand_url
    return None


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
        base_netloc = urllib.parse.urlparse(url).netloc.lower()

        # Check preferred h1 classes first
        h1_preferred = soup.select_one("h1.title, h1.story-title, h1.entry-title, h1.name")
        if h1_preferred:
            txt = h1_preferred.get_text(strip=True)
            if txt and txt.lower() != base_netloc and not re.search(r"\.(store|com|vn|net|org|top|info|fit|site)$", txt.lower()):
                title = txt

        if not title:
            # Check all h1s, skipping domain/brand headers
            for h1_tag in soup.find_all("h1"):
                txt = h1_tag.get_text(strip=True)
                h1_classes = " ".join(h1_tag.get("class", [])).lower()
                if any(k in h1_classes for k in ["logo", "brand", "site-title", "header"]):
                    continue
                txt_clean = txt.lower().strip()
                if txt_clean == base_netloc or txt_clean in base_netloc or re.search(r"\.(store|com|vn|net|org|top|info|fit|site)$", txt_clean):
                    continue
                if txt:
                    title = txt
                    break

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
            m = re.search(r"Tác giả\s*[:\s]*\s*([^<\n\r,]+)", html, re.IGNORECASE)
            if m:
                cand = m.group(1).strip()
                if cand and cand.lower() not in ["đang cập nhật", "updating", "chưa rõ"]:
                    author = cand

        author = re.sub(r"<[^>]+>", "", author).strip()
        author = re.sub(r"^[–—\-:\s]+|[–—\-:\s]+$", "", author).strip()
        if not author or author.lower() in ["đang cập nhật", "updating", "chưa rõ"]:
            author = "Không rõ"

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

    def extract_chapter_list(self, html: str, url: str, fetcher: Any = None, depth: int = 0) -> List[ChapterItem]:
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
                raw_t = title_span.get_text(separator=" ", strip=True)
            elif date_span:
                clone = BeautifulSoup(str(a_tag), "html.parser")
                for ds in clone.select(".chapter-date, .chap-date"):
                    ds.decompose()
                raw_t = clone.get_text(separator=" ", strip=True)
            else:
                raw_t = a_tag.get_text(separator=" ", strip=True)

            clean_t = re.sub(r"^\s*\d+\s*(?=(?:chương|chap|chapter|hồi)\b)", "", raw_t, flags=re.I).strip()
            return clean_t or raw_t, chap_date

        def _harvest_links(curr_soup: BeautifulSoup) -> List[ChapterItem]:
            items = []

            def _container_has_chap_links(c_tag: Tag) -> bool:
                for a in c_tag.find_all("a", href=True):
                    h = a.get("href", "")
                    t = a.get_text(strip=True)
                    if re.search(r"(chuong|chapter|chap|hoi)[-_/]?\d+", h, re.I) or re.search(r"^(Chương|Hồi|Chap|Chapter)\s+\d+", t, re.I):
                        return True
                return False

            # Priority 1: dedicated main-story chapter containers (including Madara .listing-chapters_wrap / ul.version-chap)
            primary_containers = curr_soup.select(
                ".listing-chapters_wrap, ul.version-chap, #manga-chapters-holder, "
                ".es-chapters .chapter-list, #danh-sach-chuong, #list-chapter"
            )
            containers = [c for c in primary_containers if _container_has_chap_links(c)]

            if not containers:
                # Priority 2: general chapter containers, excluding sidebar/related story widgets
                raw_containers = curr_soup.select(
                    ".chapter-list, .list-chapter, .list-chapters, .chapters, "
                    "#chapters, .table-list, ul.list-chap, .box-chap, .list"
                )
                filtered = [
                    c for c in raw_containers
                    if not c.find_parent(["aside"])
                    and not c.find_parent(class_=re.compile(r"(sidebar|widget|related|popular|c-sidebar|latest-posters)", re.I))
                ]
                containers = [c for c in filtered if _container_has_chap_links(c)]

            candidate_links = []
            if containers:
                for c in containers:
                    candidate_links.extend(c.find_all("a", href=True))

            # If no containers OR container links didn't have chapter hrefs, fallback to full page search
            has_chap_anchor = any(
                re.search(r"(chuong|chapter|chap|hoi)[-_/]?\d+", a.get("href", ""), re.I)
                or re.search(r"^(Chương|Hồi|Chap|Chapter)\s+\d+", a.get_text(strip=True), re.I)
                for a in candidate_links
            )
            if not candidate_links or not has_chap_anchor:
                candidate_links = []
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

        def _fetch_ajax_chapters() -> List[ChapterItem]:
            ajax_items: List[ChapterItem] = []
            if not fetcher:
                return ajax_items

            # 1. story_core_load_frontend_chapters (e.g. truyendecu.store, Truyện Core plugin)
            if "story_core_load_frontend_chapters" in html:
                m_id = re.search(r"(?:mainStoryId|story_id)\s*[:=]\s*['\"]?(\d+)['\"]?", html)
                story_id = m_id.group(1) if m_id else None
                m_ajax = re.search(r"(?:mainAjaxurl|ajaxurl|ajax_url)\s*=\s*['\"]([^'\"]+)['\"]", html)
                ajax_url = m_ajax.group(1) if m_ajax else urllib.parse.urljoin(url, "/wp-admin/admin-ajax.php")

                if story_id and ajax_url:
                    paged = 1
                    while paged <= 100:
                        data = {
                            "action": "story_core_load_frontend_chapters",
                            "story_id": story_id,
                            "paged": paged,
                            "context": "main"
                        }
                        try:
                            resp_text = fetcher.post(ajax_url, data=data, referer=url, is_ajax=True)
                            chunk_html = ""
                            try:
                                import json
                                j = json.loads(resp_text)
                                chunk_html = j.get("data", {}).get("html", "")
                            except Exception:
                                chunk_html = resp_text

                            if not chunk_html or len(chunk_html.strip()) < 50:
                                break

                            chunk_soup = BeautifulSoup(chunk_html, "html.parser")
                            new_chaps = _harvest_links(chunk_soup)
                            if not new_chaps:
                                break
                            ajax_items.extend(new_chaps)
                            paged += 1
                        except Exception as e:
                            logger.debug(f"Error fetching story_core ajax page {paged}: {e}")
                            break

            # 2. Madara manga_get_chapters (e.g. Madara themes, laophatgia)
            if not ajax_items and ("manga_get_chapters" in html or "wp-manga-chapter" in html):
                m_id = re.search(r"(?:manga_id|post_id|data-id)\s*[:=]\s*['\"]?(\d+)['\"]?", html)
                manga_id = m_id.group(1) if m_id else None
                m_ajax = re.search(r"(?:ajaxurl|ajax_url)\s*=\s*['\"]([^'\"]+)['\"]", html)
                ajax_url = m_ajax.group(1) if m_ajax else urllib.parse.urljoin(url, "/wp-admin/admin-ajax.php")

                if manga_id and ajax_url:
                    data = {
                        "action": "manga_get_chapters",
                        "manga": manga_id
                    }
                    try:
                        resp_text = fetcher.post(ajax_url, data=data, referer=url, is_ajax=True)
                        if resp_text and len(resp_text) > 100:
                            chunk_soup = BeautifulSoup(resp_text, "html.parser")
                            new_chaps = _harvest_links(chunk_soup)
                            if new_chaps:
                                ajax_items.extend(new_chaps)
                    except Exception as e:
                        logger.debug(f"Error fetching manga_get_chapters ajax: {e}")

            return ajax_items

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

        # Harvest chapters: check AJAX first, otherwise harvest HTML
        ajax_chapters = _fetch_ajax_chapters()
        if ajax_chapters:
            chapters = ajax_chapters
        else:
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

        # Normalize existing chapters first to find the true last chapter
        chapters = _normalize_chapter_order(chapters)

        # Proactively check for continuation links / mirror domains (e.g. vivutruyen2 -> vivutruyen)
        if fetcher and chapters and len(chapters) < 100 and depth < 2:
            continuation_depth = 0
            while continuation_depth < 3:
                last_item = chapters[-1]
                try:
                    last_html = fetcher.fetch(last_item.url, referer=url)
                    last_soup = BeautifulSoup(last_html, "html.parser")
                    cont_url = _find_in_content_continuation_link(last_soup, last_item.url)
                    if not cont_url:
                        break

                    logger.info(f"Discovered in-content continuation link: {cont_url}")
                    cont_parsed = urllib.parse.urlparse(cont_url)
                    cont_path_parts = [p for p in cont_parsed.path.split("/") if p]
                    new_story_urls = []
                    if len(cont_path_parts) >= 2:
                        cand_story_path = "/" + "/".join(cont_path_parts[:-1]) + "/"
                        cand_story_url = urllib.parse.urlunparse((
                            cont_parsed.scheme, cont_parsed.netloc, cand_story_path, "", "", ""
                        ))
                        new_story_urls.append(cand_story_url)
                    new_story_urls.append(cont_url)

                    added_count = 0
                    current_seen = {c.url.rstrip("/") for c in chapters}
                    for st_url in new_story_urls:
                        try:
                            st_html = fetcher.fetch(st_url, referer=last_item.url)
                            more_items = self.extract_chapter_list(st_html, st_url, fetcher, depth=depth + 1)
                            if more_items:
                                for itm in more_items:
                                    norm_u = itm.url.rstrip("/")
                                    if norm_u not in current_seen:
                                        current_seen.add(norm_u)
                                        chapters.append(itm)
                                        added_count += 1
                                if added_count > 0:
                                    break
                        except Exception as e:
                            logger.debug(f"Failed to harvest from continuation url {st_url}: {e}")

                    if added_count == 0:
                        break
                    chapters = _normalize_chapter_order(chapters)
                    continuation_depth += 1
                except Exception as e:
                    logger.debug(f"Continuation check error: {e}")
                    break

        return _normalize_chapter_order(chapters)

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
        content_div = None
        for sel in [
            "#chapter-content", ".chapter-content", "#chapter-c", ".chapter-c",
            ".reading", ".reading-content", ".entry-content", ".post-content",
            ".es-post .content", ".content.es-fs-md",
            "#bookContentBody", ".chapter-body", ".content-story",
            "#content", ".content", "article"
        ]:
            found = soup.select_one(sel)
            if found:
                content_div = found
                break

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

        # 3. Next Chapter link detection (must belong to the same domain or mirror domain)
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
                if _is_same_or_mirror_domain(cand_url, url) and cand_url.rstrip("/") != url.rstrip("/"):
                    next_url = cand_url

        if not next_url:
            for a in soup.find_all("a", href=True):
                txt = a.get_text(separator=" ", strip=True).lower()
                if (
                    txt in ["chương tiếp", "chương sau", "tiếp theo", "next chapter", "next", "sau >"]
                    or re.search(r"^(chương tiếp|chương sau|tiếp theo|next chapter|next\b|sau\b)", txt, re.I)
                ):
                    raw_href = a["href"]
                    if not raw_href.startswith("#") and "javascript:" not in raw_href and not _is_pagination_link(a, raw_href):
                        cand_url = urllib.parse.urljoin(url, raw_href)
                        if _is_same_or_mirror_domain(cand_url, url) and cand_url.rstrip("/") != url.rstrip("/"):
                            next_url = cand_url
                            break

        if not next_url:
            next_url = _find_in_content_continuation_link(soup, url, title)

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
