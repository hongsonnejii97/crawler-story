"""
FastAPI Server & Web API for Story Novel Crawler (Story-Transfer ZIP Exporter).
Provides real-time crawling monitoring, batch queue management, ad filtering, and ZIP package downloads.
"""
import os
import sys
import json
import base64
import zipfile
import subprocess
import threading
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.fetcher import Fetcher
from core.cleaner import ContentCleaner
from core.zip_builder import ZipBuilder, resolve_writable_output_dir
from core.crawler import StoryCrawler
from core.config_manager import load_config, save_config
from core.site_handlers.base import StoryInfo, ChapterContent

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

app = FastAPI(title="Novel Story Crawler To Story-Transfer ZIP", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR = resolve_writable_output_dir("output")
MEMORY_ZIP_CACHE: Dict[str, Dict[str, Any]] = {}

def _register_zip_in_memory(
    zip_path: str,
    story_title: str,
    story_count: int = 1,
    chapters_count: int = 0
) -> Optional[str]:
    """Store generated ZIP bytes in memory and return base64 string for serverless browser persistence."""
    if not zip_path or not os.path.exists(zip_path):
        return None
    try:
        fname = os.path.basename(zip_path)
        with open(zip_path, "rb") as f:
            raw_bytes = f.read()
        now_ts = datetime.now().timestamp()
        size_kb = round(len(raw_bytes) / 1024, 1)
        size_mb = round(len(raw_bytes) / (1024 * 1024), 2)
        b64_str = base64.b64encode(raw_bytes).decode("ascii") if len(raw_bytes) <= 15 * 1024 * 1024 else None

        MEMORY_ZIP_CACHE[fname] = {
            "name": fname,
            "story_title": story_title,
            "story_count": story_count,
            "chapters_count": chapters_count,
            "size_kb": size_kb,
            "size_mb": size_mb,
            "created_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "timestamp": now_ts,
            "bytes": raw_bytes
        }
        # Keep memory cache bounded to 20 most recent archives
        if len(MEMORY_ZIP_CACHE) > 20:
            oldest_key = min(MEMORY_ZIP_CACHE.keys(), key=lambda k: MEMORY_ZIP_CACHE[k]["timestamp"])
            MEMORY_ZIP_CACHE.pop(oldest_key, None)
        return b64_str
    except Exception:
        return None

class CrawlerState:
    def __init__(self):
        self.lock = threading.Lock()
        self.is_running = False
        self.should_cancel = False
        self.current_story_idx = 0
        self.total_stories = 0
        self.current_story_title = ""
        self.current_chapter = 0
        self.total_chapters = 0
        self.current_chapter_title = ""
        self.percentage = 0.0
        self.status = "idle"
        self.logs: List[Dict[str, str]] = []
        self.completed_files: List[Dict[str, Any]] = []
        self.active_crawler: Optional[StoryCrawler] = None

    def log(self, level: str, message: str):
        with self.lock:
            ts = datetime.now().strftime("%H:%M:%S")
            self.logs.append({"time": ts, "level": level, "message": message})
            if len(self.logs) > 300:
                self.logs.pop(0)

    def reset(self, total_stories: int):
        with self.lock:
            self.is_running = True
            self.should_cancel = False
            self.current_story_idx = 0
            self.total_stories = total_stories
            self.current_story_title = ""
            self.current_chapter = 0
            self.total_chapters = 0
            self.current_chapter_title = ""
            self.percentage = 0.0
            self.status = "running"
            self.logs = []
            self.completed_files = []

    def get_progress_data(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "is_running": self.is_running,
                "status": self.status,
                "current_story_idx": self.current_story_idx,
                "total_stories": self.total_stories,
                "current_story_title": self.current_story_title,
                "current_chapter": self.current_chapter,
                "total_chapters": self.total_chapters,
                "current_chapter_title": self.current_chapter_title,
                "percentage": self.percentage,
                "logs": self.logs[-60:],
                "completed_files": self.completed_files
            }

state = CrawlerState()

class CrawlRequest(BaseModel):
    urls: List[str]
    start_chapter: int = 1
    end_chapter: Optional[int] = None
    max_workers: int = 3
    request_delay: float = 0.3
    export_mode: str = "individual"  # "individual" | "batch" | "both"

def _run_batch_crawler(request: CrawlRequest):
    cfg = load_config()
    cleaner = ContentCleaner(
        custom_phrases=cfg.get("custom_ad_phrases", []),
        min_paragraph_length=1
    )
    zip_builder = ZipBuilder()

    state.reset(len(request.urls))
    state.log("info", f"Bắt đầu hàng đợi cào truyện ({len(request.urls)} đường link)...")

    create_individual = request.export_mode in ("individual", "both")
    create_batch = request.export_mode in ("batch", "both")
    stories_bundle: List[Tuple[StoryInfo, List[ChapterContent]]] = []

    for idx, url in enumerate(request.urls, start=1):
        if state.should_cancel:
            state.log("warning", "Quá trình đã bị hủy bởi người dùng.")
            break

        url = url.strip()
        if not url:
            continue

        with state.lock:
            state.current_story_idx = idx
            state.current_story_title = url
            state.current_chapter = 0
            state.total_chapters = 0
            state.percentage = 0.0

        state.log("info", f"[{idx}/{len(request.urls)}] Bắt đầu xử lý: {url}")

        crawler = StoryCrawler(
            cleaner=cleaner,
            zip_builder=zip_builder,
            output_dir=OUTPUT_DIR
        )
        state.active_crawler = crawler

        def on_progress(p: Dict[str, Any]):
            with state.lock:
                state.current_story_title = p.get("story_title", state.current_story_title)
                state.current_chapter = p.get("current", 0)
                state.total_chapters = p.get("total", 0)
                state.percentage = p.get("percentage", 0.0)
                state.current_chapter_title = p.get("current_chapter_title", "")

            level = "info"
            if p.get("status") == "error":
                level = "error"
            elif p.get("status") == "done":
                level = "success"

            state.log(level, p.get("message", ""))

        try:
            result = crawler.crawl_story(
                url=url,
                start_chapter=request.start_chapter,
                end_chapter=request.end_chapter,
                max_workers=request.max_workers,
                request_delay=request.request_delay,
                progress_callback=on_progress,
                create_individual_zip=create_individual
            )
            if result.get("status") == "success":
                s_info = result.pop("story_info", None)
                s_chaps = result.pop("chapters", None)
                if s_info and s_chaps:
                    stories_bundle.append((s_info, s_chaps))

                if create_individual and result.get("file_name"):
                    b64_data = _register_zip_in_memory(
                        zip_path=result.get("file_path", ""),
                        story_title=result.get("story_title", ""),
                        story_count=1,
                        chapters_count=result.get("chapters_crawled", 0)
                    )
                    if b64_data:
                        result["zip_base64"] = b64_data
                    with state.lock:
                        state.completed_files.append(result)
                    state.log("success", f"Đã xuất gói ZIP: '{result.get('story_title')}' -> {result.get('file_name')}")
        except Exception as e:
            state.log("error", f"Lỗi khi cào link {url}: {e}")

    # Build combined batch ZIP if requested
    if create_batch and stories_bundle and not state.should_cancel:
        try:
            state.log("info", f"Đang đóng gói gộp {len(stories_bundle)} truyện vào 1 file ZIP chung...")
            batch_zip_path = zip_builder.build_batch_zip(stories_bundle, output_dir=OUTPUT_DIR)
            size_kb = round(os.path.getsize(batch_zip_path) / 1024, 1)
            total_chaps = sum(len(chaps) for _, chaps in stories_bundle)
            b64_batch = _register_zip_in_memory(
                zip_path=batch_zip_path,
                story_title=f"Gói Gộp {len(stories_bundle)} Truyện",
                story_count=len(stories_bundle),
                chapters_count=total_chaps
            )
            batch_info = {
                "status": "success",
                "story_title": f"Gói Gộp {len(stories_bundle)} Truyện",
                "story_count": len(stories_bundle),
                "chapters_crawled": total_chaps,
                "file_path": batch_zip_path,
                "file_name": os.path.basename(batch_zip_path),
                "file_size_kb": size_kb
            }
            if b64_batch:
                batch_info["zip_base64"] = b64_batch
            with state.lock:
                state.completed_files.append(batch_info)
            state.log("success", f"Đã tạo file ZIP gộp: {os.path.basename(batch_zip_path)} ({size_kb} KB)")
        except Exception as e:
            state.log("error", f"Lỗi khi tạo file ZIP gộp: {e}")

    with state.lock:
        state.is_running = False
        state.status = "finished" if not state.should_cancel else "cancelled"
    state.log("info", f"Hoàn tất toàn bộ công việc! Tổng cộng {len(state.completed_files)} file ZIP đã tạo.")

@app.post("/api/crawl")
def start_crawl(request: CrawlRequest, background_tasks: BackgroundTasks):
    if state.is_running:
        raise HTTPException(status_code=400, detail="Một tác vụ cào truyện đang chạy. Vui lòng đợi hoặc bấm Dừng.")

    valid_urls = [u.strip() for u in request.urls if u.strip().startswith("http")]
    if not valid_urls:
        raise HTTPException(status_code=400, detail="Vui lòng nhập ít nhất 1 link truyện hợp lệ (bắt đầu bằng http:// hoặc https://).")

    request.urls = valid_urls
    background_tasks.add_task(_run_batch_crawler, request)
    return {"status": "started", "total_urls": len(valid_urls)}

@app.post("/api/cancel")
def cancel_crawl():
    if not state.is_running:
        return {"status": "not_running"}
    state.should_cancel = True
    if state.active_crawler:
        state.active_crawler.cancel()
    state.log("warning", "Đang gửi lệnh dừng đến crawler...")
    return {"status": "cancelling"}

@app.get("/api/progress")
def get_progress():
    return state.get_progress_data()

@app.get("/api/files")
def list_files():
    files = []
    seen_names = set()
    if os.path.exists(OUTPUT_DIR):
        for fname in os.listdir(OUTPUT_DIR):
            if fname.lower().endswith(".zip"):
                fpath = os.path.join(OUTPUT_DIR, fname)
                st = os.stat(fpath)
                story_title = ""
                story_count = 1
                chapters_count = 0
                try:
                    with zipfile.ZipFile(fpath, "r") as zf:
                        if "manifest.json" in zf.namelist():
                            mf = json.loads(zf.read("manifest.json").decode("utf-8"))
                            story_count = mf.get("story_count", 1)
                            s_files = mf.get("stories", [])
                            if s_files and s_files[0] in zf.namelist():
                                s_data = json.loads(zf.read(s_files[0]).decode("utf-8"))
                                story_title = s_data.get("story", {}).get("title", "")
                                chapters_count = len(s_data.get("chapters", []))
                except Exception:
                    pass

                seen_names.add(fname)
                files.append({
                    "name": fname,
                    "story_title": story_title,
                    "story_count": story_count,
                    "chapters_count": chapters_count,
                    "size_kb": round(st.st_size / 1024, 1),
                    "size_mb": round(st.st_size / (1024 * 1024), 2),
                    "created_at": datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M"),
                    "timestamp": st.st_mtime
                })

    for fname, meta in MEMORY_ZIP_CACHE.items():
        if fname not in seen_names:
            files.append({
                "name": meta["name"],
                "story_title": meta["story_title"],
                "story_count": meta["story_count"],
                "chapters_count": meta["chapters_count"],
                "size_kb": meta["size_kb"],
                "size_mb": meta["size_mb"],
                "created_at": meta["created_at"],
                "timestamp": meta["timestamp"]
            })

    files.sort(key=lambda x: x["timestamp"], reverse=True)
    return {"files": files}

@app.get("/api/download/{filename}")
def download_file(filename: str):
    safe_name = os.path.basename(filename)
    file_path = os.path.join(OUTPUT_DIR, safe_name)
    if os.path.exists(file_path):
        return FileResponse(file_path, filename=safe_name, media_type="application/zip")
    if safe_name in MEMORY_ZIP_CACHE:
        return Response(
            content=MEMORY_ZIP_CACHE[safe_name]["bytes"],
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}"'}
        )
    raise HTTPException(status_code=404, detail="File không tồn tại.")

@app.delete("/api/files/{filename}")
def delete_file(filename: str):
    safe_name = os.path.basename(filename)
    file_path = os.path.join(OUTPUT_DIR, safe_name)
    removed = False
    if os.path.exists(file_path):
        os.remove(file_path)
        removed = True
    if safe_name in MEMORY_ZIP_CACHE:
        MEMORY_ZIP_CACHE.pop(safe_name, None)
        removed = True
    if removed:
        return {"status": "deleted", "filename": safe_name}
    raise HTTPException(status_code=404, detail="File không tồn tại.")

@app.post("/api/open-folder")
def open_output_folder():
    try:
        if sys.platform == "win32":
            os.startfile(OUTPUT_DIR)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", OUTPUT_DIR])
        else:
            subprocess.Popen(["xdg-open", OUTPUT_DIR])
        return {"status": "opened", "path": OUTPUT_DIR}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/config")
def get_config():
    return load_config()

@app.post("/api/config")
def update_config(data: Dict[str, Any]):
    current = load_config()
    current.update(data)
    save_config(current)
    return {"status": "saved", "config": current}

class CleanPreviewRequest(BaseModel):
    sample_text: Optional[str] = None
    url: Optional[str] = None

@app.post("/api/preview-clean")
def preview_clean(req: CleanPreviewRequest):
    cfg = load_config()
    cleaner = ContentCleaner(custom_phrases=cfg.get("custom_ad_phrases", []))

    if req.url:
        fetcher = Fetcher()
        try:
            from core.site_handlers import get_handler_for_url
            html_text = fetcher.fetch(req.url)
            handler = get_handler_for_url(req.url)
            content = handler.extract_chapter_content(html_text, req.url, cleaner)
            return {
                "title": content.title,
                "paragraphs_count": len(content.paragraphs),
                "paragraphs": content.paragraphs[:15]
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Lỗi kiểm tra link: {e}")
    elif req.sample_text:
        cleaned = cleaner.clean_text_into_paragraphs(req.sample_text)
        return {
            "title": "Xem trước mẫu văn bản",
            "paragraphs_count": len(cleaned),
            "paragraphs": cleaned
        }
    else:
        raise HTTPException(status_code=400, detail="Cần cung cấp URL chương hoặc đoạn văn bản mẫu.")

@app.get("/")
def serve_index():
    index_path = os.path.join("web", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Trang chủ Crawler đang chuẩn bị...</h1>")
