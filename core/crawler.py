"""
Master Story Crawler module.
Manages story crawling lifecycle, concurrency, progress tracking, and Word document compilation.
"""
import os
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Callable, Dict, Any

from .fetcher import Fetcher
from .cleaner import ContentCleaner
from .doc_builder import DocBuilder
from .site_handlers import get_handler_for_url
from .site_handlers.base import StoryInfo, ChapterItem, ChapterContent

logger = logging.getLogger("StoryCrawler")

class StoryCrawler:
    def __init__(
        self,
        fetcher: Optional[Fetcher] = None,
        cleaner: Optional[ContentCleaner] = None,
        doc_builder: Optional[DocBuilder] = None,
        output_dir: str = "output"
    ):
        self.fetcher = fetcher or Fetcher()
        self.cleaner = cleaner or ContentCleaner()
        self.doc_builder = doc_builder or DocBuilder()
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
        request_delay: float = 0.5,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        """
        Crawl a novel from URL and save into a Word document.
        
        progress_callback receives dict:
        {
            "status": "fetching_info" | "crawling_chapters" | "saving_doc" | "done" | "error",
            "story_title": str,
            "current": int,
            "total": int,
            "percentage": float,
            "current_chapter_title": str,
            "message": str
        }
        """
        self.is_cancelled = False
        start_time = time.time()

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
            html = self.fetcher.fetch(url)
        except Exception as e:
            _notify("error", f"Không thể tải trang truyện: {e}")
            raise

        story_info = handler.extract_story_info(html, url)
        self._current_story_title = story_info.title
        _notify("fetching_info", f"Tìm thấy truyện: '{story_info.title}' (Tác giả: {story_info.author})")

        # 2. Extract chapters
        _notify("fetching_info", "Đang trích xuất danh sách chương...")
        chapter_items = handler.extract_chapter_list(html, url, self.fetcher)

        # Fallback: if no chapter list found, maybe the URL is already a single chapter URL
        if not chapter_items:
            _notify("fetching_info", "Không thấy danh sách chương, thử chế độ duyệt chương tiếp...")
            first_chap = handler.extract_chapter_content(html, url, self.cleaner)
            if first_chap and first_chap.paragraphs:
                chapter_items = [ChapterItem(index=1, title=first_chap.title, url=url)]

        if not chapter_items:
            err_msg = "Không tìm thấy chương nào từ đường link này. Vui lòng kiểm tra lại link hoặc thử link chương 1."
            _notify("error", err_msg)
            raise ValueError(err_msg)

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

        # Helper to fetch and parse single chapter
        def _fetch_one_chapter(pos_idx: int, item: ChapterItem) -> tuple[int, ChapterContent]:
            if self.is_cancelled:
                raise InterruptedError("Crawl cancelled by user.")

            chap_html = self.fetcher.fetch(item.url, referer=url)
            content = handler.extract_chapter_content(chap_html, item.url, self.cleaner)
            # Ensure title matches chapter list if extracted title is generic
            if not content.title or content.title == "Chương không tiêu đề":
                content.title = item.title

            if request_delay > 0:
                time.sleep(request_delay)

            return pos_idx, content

        # Concurrency mode or Sequential
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
                        # Create a placeholder indicating missing chapter
                        pos_idx = selected_items.index(item)
                        downloaded_chapters[pos_idx] = ChapterContent(
                            title=item.title,
                            url=item.url,
                            paragraphs=[f"[Lỗi tải chương: {e}]"]
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
            # Sequential mode
            for i, item in enumerate(selected_items):
                if self.is_cancelled:
                    break
                try:
                    pos_idx, content = _fetch_one_chapter(i, item)
                    downloaded_chapters[pos_idx] = content
                except Exception as e:
                    logger.error(f"Error crawling chapter '{item.title}': {e}")
                    downloaded_chapters[i] = ChapterContent(
                        title=item.title,
                        url=item.url,
                        paragraphs=[f"[Lỗi tải chương: {e}]"]
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

        # Filter out any Nones
        final_chapters = [c for c in downloaded_chapters if c is not None]

        # 5. Compile into Word file
        _notify("saving_doc", f"Đang tổng hợp {len(final_chapters)} chương vào file Word (.docx)...", total_to_crawl, total_to_crawl)

        docx_path = self.doc_builder.build_story_document(
            story_info=story_info,
            chapters=final_chapters,
            output_dir=self.output_dir
        )

        elapsed = round(time.time() - start_time, 1)
        doc_size_mb = round(os.path.getsize(docx_path) / (1024 * 1024), 2)

        result = {
            "status": "success",
            "story_title": story_info.title,
            "author": story_info.author,
            "chapters_crawled": len(final_chapters),
            "file_path": docx_path,
            "file_name": os.path.basename(docx_path),
            "file_size_mb": doc_size_mb,
            "elapsed_seconds": elapsed,
            "message": f"Thành công! Đã lưu {len(final_chapters)} chương vào file Word: {os.path.basename(docx_path)} ({doc_size_mb} MB) trong {elapsed}s."
        }

        _notify("done", result["message"], len(final_chapters), len(final_chapters))
        return result
