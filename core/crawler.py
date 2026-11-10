"""
Master Story Crawler module.
Manages story crawling lifecycle, concurrency, progress tracking, and Story-Transfer ZIP packaging.
"""
import os
import html
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Callable, Dict, Any

from .fetcher import Fetcher
from .cleaner import ContentCleaner
from .zip_builder import ZipBuilder
from .site_handlers import get_handler_for_url
from .site_handlers.base import StoryInfo, ChapterItem, ChapterContent
from .site_handlers.universal import (
    slugify_vi,
    format_story_title_with_code,
    format_chapter_title_with_code
)

logger = logging.getLogger("StoryCrawler")

class StoryCrawler:
    def __init__(
        self,
        fetcher: Optional[Fetcher] = None,
        cleaner: Optional[ContentCleaner] = None,
        zip_builder: Optional[ZipBuilder] = None,
        output_dir: str = "output"
    ):
        self.fetcher = fetcher or Fetcher()
        self.cleaner = cleaner or ContentCleaner()
        self.zip_builder = zip_builder or ZipBuilder()
        self.output_dir = output_dir
        self.is_cancelled = False

    def cancel(self):
        """Signal crawler to stop."""
        self.is_cancelled = True

    def crawl_story(
        self,
        url: str,
        start_chapter: int = 1,
        end_chapter: Optional[int] = None,
        max_workers: int = 3,
        request_delay: float = 0.3,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        create_individual_zip: bool = True,
        story_code: Optional[str] = ""
    ) -> Dict[str, Any]:
        """
        Crawl a novel from URL and package into a story-transfer .zip archive.
        """
        self.is_cancelled = False
        start_time = time.time()
        clean_code = (story_code or "").strip()

        def _notify(status: str, msg: str, current: int = 0, total: int = 0, cur_title: str = ""):
            if progress_callback:
                pct = round((current / total * 100), 1) if total > 0 else 0
                progress_callback({
                    "status": status,
                    "story_title": getattr(self, "_current_story_title", ""),
                    "current": current,
                    "total": total,
                    "percentage": pct,
                    "current_chapter_title": cur_title,
                    "message": msg
                })

        _notify("fetching_info", f"Đang kết nối và lấy thông tin truyện từ: {url}")

        handler = get_handler_for_url(url)
        logger.info(f"Using handler '{handler.name}' for URL: {url}")

        # 1. Fetch story page
        try:
            page_html = self.fetcher.fetch(url)
        except Exception as e:
            _notify("error", f"Không thể tải trang truyện: {e}")
            raise

        try:
            story_info = handler.extract_story_info(page_html, url)
        except Exception as e:
            _notify("error", str(e))
            raise

        if clean_code:
            story_info.story_code = clean_code
            story_info.title = format_story_title_with_code(story_info.title, clean_code)
            story_info.slug = slugify_vi(clean_code)

        self._current_story_title = story_info.title
        _notify("fetching_info", f"Tìm thấy truyện: '{story_info.title}' (ID: {story_info.original_id})")

        # 2. Extract chapters
        _notify("fetching_info", "Đang trích xuất danh sách chương...")
        chapter_items = handler.extract_chapter_list(page_html, url, self.fetcher)

        # Fallback: if no chapter list found, maybe the URL is already a single chapter URL
        if not chapter_items:
            _notify("fetching_info", "Không thấy danh sách chương, thử chế độ duyệt chương tiếp...")
            first_chap = handler.extract_chapter_content(page_html, url, self.cleaner)
            if first_chap and first_chap.paragraphs:
                chapter_items = [ChapterItem(
                    index=1,
                    title=first_chap.title,
                    url=url,
                    slug=first_chap.slug,
                    date=first_chap.date
                )]

        if not chapter_items:
            err_msg = "Không tìm thấy chương nào từ đường link này. Vui lòng kiểm tra lại link hoặc thử link chương 1."
            _notify("error", err_msg)
            raise ValueError(err_msg)

        if clean_code:
            for item in chapter_items:
                item.title = format_chapter_title_with_code(item.title, item.index, clean_code)

        total_available = len(chapter_items)
        _notify("fetching_info", f"Tổng cộng phát hiện {total_available} chương.")

        # 3. Filter chapter range
        start_idx = max(1, start_chapter)
        end_idx = min(total_available, end_chapter) if end_chapter else total_available

        if start_idx > total_available:
            start_idx = 1
        if end_idx < start_idx:
            end_idx = total_available

        selected_items = [c for c in chapter_items if start_idx <= c.index <= end_idx]
        total_to_crawl = len(selected_items)
        _notify("crawling_chapters", f"Bắt đầu tải {total_to_crawl} chương (từ chương {start_idx} đến {end_idx})...", 0, total_to_crawl)

        # 4. Crawl chapters
        downloaded_chapters: List[Optional[ChapterContent]] = [None] * total_to_crawl
        completed_count = 0

        def _fetch_one_chapter(pos_idx: int, item: ChapterItem) -> tuple[int, ChapterContent]:
            if self.is_cancelled:
                raise InterruptedError("Crawl cancelled by user.")

            chap_html = self.fetcher.fetch(item.url, referer=url)
            content = handler.extract_chapter_content(chap_html, item.url, self.cleaner)

            content.number = item.index
            if not content.title or content.title == "Chương không tiêu đề":
                content.title = item.title
            if clean_code:
                content.title = format_chapter_title_with_code(content.title, item.index, clean_code)
            if not content.slug and item.slug:
                content.slug = item.slug
            if item.date and not content.date:
                content.date = item.date

            if request_delay > 0:
                time.sleep(request_delay)

            return pos_idx, content

        if max_workers > 1 and total_to_crawl > 1:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(_fetch_one_chapter, i, item): item
                    for i, item in enumerate(selected_items)
                }

                for future in as_completed(futures):
                    if self.is_cancelled:
                        executor.shutdown(wait=False, cancel_futures=True)
                        break

                    item = futures[future]
                    try:
                        pos_idx, content = future.result()
                        downloaded_chapters[pos_idx] = content
                        completed_count += 1
                        _notify(
                            "crawling_chapters",
                            f"Đã tải ({completed_count}/{total_to_crawl}): {content.title}",
                            completed_count,
                            total_to_crawl,
                            content.title
                        )
                    except Exception as e:
                        logger.error(f"Error crawling chapter '{item.title}': {e}")
                        pos_idx = selected_items.index(item)
                        err_text = f"[Lỗi tải chương: {e}]"
                        downloaded_chapters[pos_idx] = ChapterContent(
                            title=item.title,
                            url=item.url,
                            paragraphs=[err_text],
                            html_content=f"<p>{html.escape(err_text)}</p>",
                            number=item.index,
                            slug=item.slug or f"chuong-{item.index}"
                        )
                        completed_count += 1
                        _notify(
                            "crawling_chapters",
                            f"Lỗi tải chương ({completed_count}/{total_to_crawl}): {item.title}",
                            completed_count,
                            total_to_crawl,
                            item.title
                        )
        else:
            for i, item in enumerate(selected_items):
                if self.is_cancelled:
                    break
                try:
                    pos_idx, content = _fetch_one_chapter(i, item)
                    downloaded_chapters[pos_idx] = content
                except Exception as e:
                    logger.error(f"Error crawling chapter '{item.title}': {e}")
                    err_text = f"[Lỗi tải chương: {e}]"
                    downloaded_chapters[i] = ChapterContent(
                        title=item.title,
                        url=item.url,
                        paragraphs=[err_text],
                        html_content=f"<p>{html.escape(err_text)}</p>",
                        number=item.index,
                        slug=item.slug or f"chuong-{item.index}"
                    )
                completed_count += 1
                cur_title = downloaded_chapters[i].title if downloaded_chapters[i] else item.title
                _notify(
                    "crawling_chapters",
                    f"Đã tải ({completed_count}/{total_to_crawl}): {cur_title}",
                    completed_count,
                    total_to_crawl,
                    cur_title
                )

        if self.is_cancelled:
            _notify("error", "Đã hủy quá trình crawler theo yêu cầu của bạn.")
            return {"status": "cancelled", "story_title": story_info.title}

        final_chapters = [c for c in downloaded_chapters if c is not None]

        # 4b. Sequential 'next_url' continuation fallback:
        # If the user did not cap end_chapter (or cap was not reached) and the last crawled chapter
        # points to a valid unvisited next_url (e.g. when starting from a Chapter 1 URL or a site
        # that only renders partial chapters on the main page), follow next_url until the final chapter.
        visited_chap_urls = {url.rstrip("/")}
        for item in chapter_items:
            visited_chap_urls.add(item.url.rstrip("/"))
        for ch in final_chapters:
            visited_chap_urls.add(ch.url.rstrip("/"))

        while final_chapters and not self.is_cancelled:
            if end_chapter and len(final_chapters) >= (end_chapter - start_idx + 1):
                break
            last_chap = final_chapters[-1]
            nxt = last_chap.next_url
            if not nxt or nxt.rstrip("/") in visited_chap_urls:
                break
            visited_chap_urls.add(nxt.rstrip("/"))
            try:
                nxt_html = self.fetcher.fetch(nxt, referer=last_chap.url)
                nxt_content = handler.extract_chapter_content(nxt_html, nxt, self.cleaner)
                if not nxt_content or len(nxt_content.paragraphs) < 2:
                    break
                nxt_num = (last_chap.number or len(final_chapters)) + 1
                nxt_content.number = nxt_num
                if clean_code:
                    nxt_content.title = format_chapter_title_with_code(nxt_content.title, nxt_num, clean_code)
                final_chapters.append(nxt_content)
                total_now = len(final_chapters)
                _notify(
                    "crawling_chapters",
                    f"Đã tải tiếp ({total_now}): {nxt_content.title}",
                    total_now,
                    total_now,
                    nxt_content.title
                )
                if request_delay > 0:
                    time.sleep(request_delay)
            except Exception as e:
                logger.debug(f"Stopped following next_url {nxt}: {e}")
                break

        # Ensure all chapter titles adhere to story_code formatting
        if clean_code:
            for ch in final_chapters:
                ch.title = format_chapter_title_with_code(ch.title, ch.number, clean_code)

        # 5. Package into Story-Transfer ZIP file
        zip_path = ""
        zip_size_kb = 0.0
        zip_size_mb = 0.0
        if create_individual_zip:
            _notify("saving_zip", f"Đang đóng gói {len(final_chapters)} chương vào file ZIP (story-transfer)...", total_to_crawl, total_to_crawl)
            zip_path = self.zip_builder.build_story_zip(
                story_info=story_info,
                chapters=final_chapters,
                output_dir=self.output_dir
            )
            size_bytes = os.path.getsize(zip_path)
            zip_size_kb = round(size_bytes / 1024, 1)
            zip_size_mb = round(size_bytes / (1024 * 1024), 2)

        elapsed = round(time.time() - start_time, 1)

        result = {
            "status": "success",
            "story_title": story_info.title,
            "original_id": story_info.original_id,
            "author": story_info.author,
            "chapters_crawled": len(final_chapters),
            "file_path": zip_path,
            "file_name": os.path.basename(zip_path) if zip_path else "",
            "file_size_kb": zip_size_kb,
            "file_size_mb": zip_size_mb,
            "elapsed_seconds": elapsed,
            "story_info": story_info,
            "chapters": final_chapters,
            "message": (
                f"Thành công! Đã đóng gói {len(final_chapters)} chương vào file ZIP: "
                f"{os.path.basename(zip_path)} ({zip_size_kb} KB) trong {elapsed}s."
                if zip_path else
                f"Đã tải xong {len(final_chapters)} chương của '{story_info.title}' trong {elapsed}s."
            )
        }

        _notify("done", result["message"], len(final_chapters), len(final_chapters))
        return result
