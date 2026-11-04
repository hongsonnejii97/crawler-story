"""
FastAPI Server & Web API for Story Novel Crawler.
Provides real-time crawling monitoring, batch queue management, ad filtering, and docx downloads.
"""
import os
import sys
import time
import subprocess
import threading
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.fetcher import Fetcher
from core.cleaner import ContentCleaner
from core.doc_builder import DocBuilder
from core.crawler import StoryCrawler
from core.config_manager import load_config, save_config

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

app = FastAPI(title="Novel Story Crawler To Word", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR = os.path.abspath("output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Global Crawler State
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
        self.status = "idle"  # idle, running, finished, error, cancelled
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
                "logs": self.logs[-60:],  # return latest 60 logs
                "completed_files": self.completed_files
            }

state = CrawlerState()

class CrawlRequest(BaseModel):
    urls: List[str]
    start_chapter: int = 1
    end_chapter: Optional[int] = None
    max_workers: int = 3
    request_delay: float = 0.3
    include_toc: bool = True
    font_name: str = "Times New Roman"
    font_size: int = 12

def _run_batch_crawler(request: CrawlRequest):
    cfg = load_config()
    cleaner = ContentCleaner(
        custom_phrases=cfg.get("custom_ad_phrases", []),
        min_paragraph_length=1
    )
    doc_builder = DocBuilder(
        font_name=request.font_name,
        font_size=request.font_size
    )

    state.reset(len(request.urls))
    state.log("info", f"Bắt đầu hàng đợi cào truyện ({len(request.urls)} đường link)...")

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
            doc_builder=doc_builder,
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
                progress_callback=on_progress
            )
            if result.get("status") == "success":
                with state.lock:
                    state.completed_files.append(result)
                state.log("success", f"Đã hoàn thành truyện: '{result.get('story_title')}' -> {result.get('file_name')}")
        except Exception as e:
            state.log("error", f"Lỗi khi cào link {url}: {e}")

    with state.lock:
        state.is_running = False
        state.status = "finished" if not state.should_cancel else "cancelled"
    state.log("info", f"Hoàn tất toàn bộ công việc! Tổng cộng {len(state.completed_files)} file Word đã tạo.")

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
    if os.path.exists(OUTPUT_DIR):
        for fname in os.listdir(OUTPUT_DIR):
            if fname.lower().endswith(".docx"):
                fpath = os.path.join(OUTPUT_DIR, fname)
                st = os.stat(fpath)
                files.append({
                    "name": fname,
                    "size_mb": round(st.st_size / (1024 * 1024), 2),
                    "created_at": datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M"),
                    "timestamp": st.st_mtime
                })
    files.sort(key=lambda x: x["timestamp"], reverse=True)
    return {"files": files}

@app.get("/api/download/{filename}")
def download_file(filename: str):
    safe_name = os.path.basename(filename)
    file_path = os.path.join(OUTPUT_DIR, safe_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File không tồn tại.")
    return FileResponse(file_path, filename=safe_name, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

@app.delete("/api/files/{filename}")
def delete_file(filename: str):
    safe_name = os.path.basename(filename)
    file_path = os.path.join(OUTPUT_DIR, safe_name)
    if os.path.exists(file_path):
        os.remove(file_path)
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
                "paragraphs": content.paragraphs[:15]  # first 15 paragraphs
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

# Serve frontend HTML
@app.get("/")
def serve_index():
    index_path = os.path.join("web", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Trang chủ Crawler đang chuẩn bị...</h1>")

