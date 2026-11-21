"""
Ad Cleaner and Content Normalizer module.
Removes ads, banner tags, translator watermarks, donation requests, and site spam.
Supports outputting both clean plain-text paragraphs and clean HTML (<p>...</p>) for WordPress import.
"""
import re
import copy
import html
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup, Tag, NavigableString

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
    r"(?:👉\s*)?(?:đọc|xem)\s*tiếp\s*tại\s*(?:đây|website|web|trang)?\s*(?:phụ|chính|mới)?(?:\s*👈)?",
    r"đọc\s*tiếp\s*tại\s*đây",
    r"(?:👉\s*)?website\s*phụ(?:\s*👈)?",
    r"(?:ấn|bấm|click)\s*(?:tiếp|vào\s*đây|để|ngay)?\s*(?:để\s*)?(?:đọc|xem)(?:\s*tiếp)?(?:\s*(?:chương|tập|phần)\s*\d+)?",
    r"chương\s*\d+\s*[-–—:]+\s*(?:ấn|bấm|click)\s*.*",
    r"^\s*(?:đọc|xem)\s*tiếp\s*[:：\-–—]*\s*(?:https?://\S*)?\s*$",
    r"theo dõi kênh telegram",
    r"chương\s*này\s*đã\s*bị\s*khoá.*",
    r"vui\s*lòng\s*ấn\s*vào\s*popup.*",
    r"ấn\s*vào\s*đây\s*để\s*mở\s*lại\s*popup.*",
    r"mời\s*quý\s*độc\s*giả\s*click\s*vào\s*link.*shopee.*",
    r"mời\s*bạn\s*click\s*ads\s*này.*",
    r"sau\s*khi\s*bấm\s*liên\s*kết.*mở\s*kh[oó]a.*",
    r"gsnh\s*và\s*đội\s*ngũ\s*editor.*cảm\s*ơn.*",
    r"monkeyd\s*và\s*đội\s*ngũ\s*editor.*cảm\s*ơn.*",
    r"truyện\s*được\s*đăng\s*tải.*monkeyd.*",
    r"^\s*chương\s*trước(?:\s+chương\s*(?:sau|tiếp))?\s*$",
    r"thử\s*tải\s*lại\s*/\s*retry",
    r"mở\s*ứng\s*dụng\s*shopee.*",
    r"mở ứng dụng shopee",
    r"click vào liên kết hoặc ảnh",
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
    ".chap-header", ".chap-nav", ".chapter-header", ".chapter-footer",
    ".chapter-box", ".box-chapter", ".reading-header", ".reading-footer",
    ".rating-box", ".donate-box", ".bottom-ads", ".top-ads", ".es-story-actions",
    ".code-block", "[class*='ai-viewport']", "[class*='ai-insert']",
    ".er-partner-info", "#er-partner-info", "[class*='er-partner-info']", "[data-affiliate-click]",
    "#chapterLockNotice", "#reopenPopupBtn", ".chap-nav-bar",
    ".lsu-panel", ".lsu-overlay", ".lsu-modal", ".lsu-popup", ".lsu-retry",
    ".lsu-cta", ".lsu-invite", ".lsu-subtext", ".lsu-note", ".lsu-thanks",
    ".actcl", "p.signature", ".signature"
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
                self.ad_regexes.append(re.compile(re.escape(p), re.IGNORECASE))

    def _strip_ad_elements(self, container: Tag) -> Tag:
        """Strip ad tags, scripts, banners and hidden elements from BeautifulSoup container."""
        for tag_name in DEFAULT_REMOVE_TAGS:
            for el in container.find_all(tag_name):
                el.decompose()

        for sel in DEFAULT_AD_SELECTORS:
            try:
                for el in container.select(sel):
                    el.decompose()
            except Exception:
                pass

        for el in container.find_all(attrs={"class": re.compile(r"(^|\s|_|-)(ad|ads|banner|qc|quang-cao|sponsor)(\s|_|-|$)", re.I)}):
            el.decompose()

        for el in container.find_all(attrs={"id": re.compile(r"(^|\s|_|-)(ad|ads|banner|qc|quang-cao|sponsor)(\s|_|-|$)", re.I)}):
            el.decompose()

        # Normalize anti-crawl <span class="fake" data-before="..."> tags into plain text
        for sp in container.select("span.fake, span[data-before], span[data-after]"):
            before_txt = sp.get("data-before", "")
            after_txt = sp.get("data-after", "")
            inner_txt = sp.get_text()
            if not inner_txt.strip() and (before_txt or after_txt):
                sp.string = f"{before_txt}{after_txt}"
            sp.unwrap()

        # Re-stitch sentences split mid-paragraph by .lsu-gate (.lsu-preview + .lsu-locked-content)
        for gate in container.select(".lsu-gate"):
            pv = gate.select_one(".lsu-preview")
            lc = gate.select_one(".lsu-locked-content")
            if pv and lc:
                pv_ps = pv.find_all("p")
                lc_ps = lc.find_all("p")
                if pv_ps and lc_ps:
                    last_pv_p = pv_ps[-1]
                    first_lc_p = lc_ps[0]
                    last_txt = last_pv_p.get_text().strip()
                    first_txt = first_lc_p.get_text().strip()
                    if last_txt and first_txt and not re.search(r'[.!?…"\'”’\])>:]$', last_txt):
                        if not last_pv_p.get_text().endswith((" ", "\xa0")) and not first_lc_p.get_text().startswith((" ", "\xa0")):
                            last_pv_p.append(" ")
                        for node in list(first_lc_p.contents):
                            last_pv_p.append(node)
                        first_lc_p.decompose()

        # Strip embedded prev/next navigation divs inside chapter containers (e.g. MonkeyD actionChangeChapter)
        for nav_div in list(container.find_all("div")):
            if nav_div.decomposed:
                continue
            if nav_div.find("a", attrs={"onclick": re.compile(r"actionChangeChapter", re.I)}) and not nav_div.find("p"):
                nav_div.decompose()

        # Strip leftover obfuscation/merge attributes on paragraphs
        for tag in container.find_all(True):
            if tag.has_attr("data-merged"):
                del tag["data-merged"]

        return container

    def clean_html_tree(self, container: Tag) -> Tag:
        """Strip ad tags and convert <br>/<p> into newline boundaries for plain text extraction."""
        container = self._strip_ad_elements(container)

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
            if regex.search(text):
                match = regex.search(text)
                if match:
                    span_len = match.end() - match.start()
                    if span_len >= len(text) * 0.4 or len(text) < 120:
                        return True
        return False

    def clean_text_into_paragraphs(self, raw_text: str) -> List[str]:
        """Convert raw text into clean, ad-free list of paragraphs."""
        text = html.unescape(raw_text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        lines = text.split("\n")
        paragraphs = []

        for line in lines:
            line = line.strip()
            line = re.sub(r"[ \t]+", " ", line)

            if not line:
                continue

            if self.is_ad_line(line):
                continue

            paragraphs.append(line)

        return paragraphs

    def clean_container(self, container: Tag) -> List[str]:
        """Take a BeautifulSoup container tag and return cleaned plain text paragraphs."""
        working_copy = copy.copy(container)
        cl_tree = self.clean_html_tree(working_copy)
        raw_text = cl_tree.get_text()
        return self.clean_text_into_paragraphs(raw_text)

    def clean_container_to_html(self, container: Tag) -> Tuple[List[str], str]:
        """
        Clean a BeautifulSoup container and return both:
        - paragraphs: List[str] (clean plain-text paragraphs)
        - html_content: str (HTML <p>...</p> blocks joined by \\r\\n for WordPress story-transfer import)
        """
        working_copy = BeautifulSoup(str(container), "html.parser")
        root = working_copy.find() or working_copy
        self._strip_ad_elements(root)

        p_tags = root.find_all("p")
        if p_tags:
            html_blocks: List[str] = []
            plain_paragraphs: List[str] = []

            # Iterate over direct children or top-level paragraphs/nodes
            for child in root.children:
                if isinstance(child, Tag):
                    if child.name == "p":
                        txt = re.sub(r"\s+", " ", child.get_text().replace("\xa0", " ")).strip()
                        if not txt or self.is_ad_line(txt):
                            continue
                        # Unwrap <a> tags inside <p> so external spam links aren't kept
                        for a_tag in child.find_all("a"):
                            a_tag.unwrap()
                        plain_paragraphs.append(txt)
                        html_blocks.append(str(child).replace("\xa0", " ").strip())
                    else:
                        # Might be a strong/em/span or a sub-div containing <p>
                        sub_ps = child.find_all("p")
                        if sub_ps:
                            for sp in sub_ps:
                                txt = re.sub(r"\s+", " ", sp.get_text().replace("\xa0", " ")).strip()
                                if not txt or self.is_ad_line(txt):
                                    continue
                                for a_tag in sp.find_all("a"):
                                    a_tag.unwrap()
                                plain_paragraphs.append(txt)
                                html_blocks.append(str(sp).replace("\xa0", " ").strip())
                        else:
                            txt = re.sub(r"\s+", " ", child.get_text().replace("\xa0", " ")).strip()
                            if txt and not self.is_ad_line(txt):
                                plain_paragraphs.append(txt)
                                html_blocks.append(f"<p>{str(child).replace('\xa0', ' ').strip()}</p>")
                elif isinstance(child, NavigableString):
                    txt = str(child).replace("\xa0", " ").strip()
                    if txt and not self.is_ad_line(txt):
                        plain_paragraphs.append(txt)
                        html_blocks.append(f"<p>{html.escape(txt)}</p>")

            if html_blocks:
                return plain_paragraphs, "\r\n".join(html_blocks)

        # Fallback for <br>-separated content (e.g. TruyenFull, WeTruyen)
        plain_paragraphs = self.clean_container(container)
        html_blocks = [f"<p>{html.escape(p)}</p>" for p in plain_paragraphs]
        return plain_paragraphs, "\r\n".join(html_blocks)

    def clean_description_to_text(self, container: Tag) -> str:
        """Clean story description/synopsis container into plain text separated by \\r\\n\\r\\n."""
        paragraphs = self.clean_container(container)
        return "\r\n\r\n".join(paragraphs)
