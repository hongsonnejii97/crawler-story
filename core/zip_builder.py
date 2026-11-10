"""
Story-Transfer ZIP Builder module.
Packages crawled stories and chapters into a WordPress-compatible 'story-transfer' .zip archive
containing manifest.json and stories/story-<id>.json.
"""
import os
import re
import json
import uuid
import zlib
import html
import zipfile
import tempfile
import urllib.parse
from datetime import datetime
from typing import List, Dict, Any, Tuple

from .site_handlers.base import StoryInfo, ChapterContent

def resolve_writable_output_dir(preferred_dir: str = "output") -> str:
    """
    Resolve a writable directory for storing generated .zip files.
    On local machines, uses ./output.
    On read-only serverless platforms (Vercel / AWS Lambda), automatically falls back to /tmp/output.
    """
    is_serverless = bool(
        os.environ.get("VERCEL")
        or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
        or os.environ.get("NOW_REGION")
    )
    if not is_serverless:
        try:
            abs_pref = os.path.abspath(preferred_dir)
            os.makedirs(abs_pref, exist_ok=True)
            test_file = os.path.join(abs_pref, ".write_test")
            with open(test_file, "w", encoding="utf-8") as tf:
                tf.write("ok")
            os.remove(test_file)
            return abs_pref
        except OSError:
            pass

    tmp_out = os.path.join(tempfile.gettempdir(), "output")
    os.makedirs(tmp_out, exist_ok=True)
    return tmp_out

def _get_base_site_url(url: str) -> str:
    """Return scheme://netloc/ from a URL."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/"
    return "https://localhost/"

class ZipBuilder:
    def __init__(self, plugin_version: str = "1.4.6", format_version: str = "1.0"):
        self.plugin_version = plugin_version
        self.format_version = format_version

    def create_story_json_data(
        self,
        story_info: StoryInfo,
        chapters: List[ChapterContent]
    ) -> Tuple[int, Dict[str, Any]]:
        """Build the dictionary for stories/story-<original_id>.json."""
        original_id = story_info.original_id
        if not original_id or original_id <= 0:
            original_id = zlib.crc32(story_info.url.encode("utf-8")) % 900000 + 10000

        story_uuid = str(uuid.uuid4())
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        chapters_payload: List[Dict[str, Any]] = []
        used_chap_ids = set()

        for idx, chap in enumerate(chapters, start=1):
            chap_num = chap.number if chap.number and chap.number > 0 else idx
            chap_id = chap.original_id
            if not chap_id or chap_id == original_id or chap_id in used_chap_ids:
                chap_id = original_id * 1000 + chap_num
            used_chap_ids.add(chap_id)

            chap_slug = chap.slug or f"chuong-{chap_num}"
            chap_date = chap.date or now_str

            chap_html = chap.html_content
            if not chap_html and chap.paragraphs:
                chap_html = "\r\n".join(f"<p>{html.escape(p)}</p>" for p in chap.paragraphs)

            chap_meta: Dict[str, List[str]] = {
                "_chapter_number": [str(chap_num)]
            }
            if chap.views and chap.views > 0:
                chap_meta["_chapter_view_count"] = [str(chap.views)]

            chapters_payload.append({
                "original_id": chap_id,
                "number": chap_num,
                "title": chap.title,
                "slug": chap_slug,
                "status": "publish",
                "date": chap_date,
                "content": chap_html,
                "excerpt": "",
                "meta": chap_meta
            })

        story_payload: Dict[str, Any] = {
            "format_version": self.format_version,
            "story": {
                "uuid": story_uuid,
                "original_id": original_id,
                "title": story_info.title,
                "slug": story_info.slug or "",
                "status": "publish",
                "date": "",
                "author": 0,
                "content": story_info.description or "",
                "excerpt": "",
                "meta": []
            },
            "authors": [],
            "taxonomies": [],
            "cover": None,
            "chapters": chapters_payload
        }

        return original_id, story_payload

    def create_manifest_data(
        self,
        source_site: str,
        story_paths: List[str],
        has_slug: bool = False
    ) -> Dict[str, Any]:
        """Build the dictionary for manifest.json."""
        return {
            "format": "story-transfer",
            "format_version": self.format_version,
            "plugin_version": self.plugin_version,
            "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source_site": source_site,
            "story_count": len(story_paths),
            "fields": {
                "slug": bool(has_slug),
                "content": True,
                "status": False,
                "date": False,
                "author": False,
                "source_url": False,
                "chapters": True,
                "cover": False,
                "taxonomies": False,
                "meta": False,
                "views": False,
                "raw_meta": False
            },
            "stories": story_paths
        }

    def build_story_zip(
        self,
        story_info: StoryInfo,
        chapters: List[ChapterContent],
        output_dir: str = "output"
    ) -> str:
        """
        Package a single story and its chapters into a story-transfer .zip archive.
        Returns the absolute path of the created .zip file.
        """
        target_dir = resolve_writable_output_dir(output_dir)

        original_id, story_data = self.create_story_json_data(story_info, chapters)
        inner_json_path = f"stories/story-{original_id}.json"
        source_site = _get_base_site_url(story_info.url)
        manifest_data = self.create_manifest_data(
            source_site,
            [inner_json_path],
            has_slug=bool(story_info.slug)
        )

        filename = f"story-transfer-{original_id}.zip"
        file_path = os.path.join(target_dir, filename)

        manifest_bytes = json.dumps(manifest_data, ensure_ascii=False, indent=4).encode("utf-8")
        story_bytes = json.dumps(story_data, ensure_ascii=False, indent=4).encode("utf-8")

        with zipfile.ZipFile(file_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", manifest_bytes)
            zf.writestr(inner_json_path, story_bytes)

        return os.path.abspath(file_path)

    def build_batch_zip(
        self,
        stories_bundle: List[Tuple[StoryInfo, List[ChapterContent]]],
        output_dir: str = "output"
    ) -> str:
        """
        Package multiple stories into a single combined story-transfer .zip archive.
        Returns the absolute path of the created .zip file.
        """
        target_dir = resolve_writable_output_dir(output_dir)
        if not stories_bundle:
            raise ValueError("Không có truyện nào để đóng gói ZIP.")

        story_paths: List[str] = []
        story_files_bytes: List[Tuple[str, bytes]] = []
        used_ids = set()

        for story_info, chapters in stories_bundle:
            original_id, story_data = self.create_story_json_data(story_info, chapters)
            while original_id in used_ids:
                original_id += 1
            used_ids.add(original_id)
            story_data["story"]["original_id"] = original_id

            inner_path = f"stories/story-{original_id}.json"
            story_paths.append(inner_path)
            story_bytes = json.dumps(story_data, ensure_ascii=False, indent=4).encode("utf-8")
            story_files_bytes.append((inner_path, story_bytes))

        source_site = _get_base_site_url(stories_bundle[0][0].url)
        has_any_slug = any(bool(s[0].slug) for s in stories_bundle)
        manifest_data = self.create_manifest_data(
            source_site,
            story_paths,
            has_slug=has_any_slug
        )
        manifest_bytes = json.dumps(manifest_data, ensure_ascii=False, indent=4).encode("utf-8")

        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"story-transfer-batch-{len(stories_bundle)}stories-{ts}.zip"
        file_path = os.path.join(target_dir, filename)

        with zipfile.ZipFile(file_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", manifest_bytes)
            for inner_path, s_bytes in story_files_bytes:
                zf.writestr(inner_path, s_bytes)

        return os.path.abspath(file_path)
