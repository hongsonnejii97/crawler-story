"""
Command-Line Interface (CLI) for Story Novel Crawler (Story-Transfer ZIP Exporter).
Allows running single or batch crawling directly from the terminal and packaging into .zip files.
"""
import os
import sys
import argparse
from typing import List, Tuple

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from core.crawler import StoryCrawler
from core.cleaner import ContentCleaner
from core.zip_builder import ZipBuilder
from core.config_manager import load_config
from core.site_handlers.base import StoryInfo, ChapterContent

def parse_args():
    parser = argparse.ArgumentParser(description="Tool Crawler Truyện Đóng Gói ZIP Chuẩn Story-Transfer (Import Website)")
    parser.add_argument("--url", "-u", type=str, help="Link truyện cần cào (ví dụ: https://thaonguyen1.giangsonnhuhoa.com/truyen/2311/)")
    parser.add_argument("--file", "-f", type=str, help="File text chứa danh sách link (mỗi dòng 1 link)")
    parser.add_argument("--start", "-s", type=int, default=1, help="Chương bắt đầu (mặc định: 1)")
    parser.add_argument("--end", "-e", type=int, default=None, help="Chương kết thúc (mặc định: hết truyện)")
    parser.add_argument("--workers", "-w", type=int, default=3, help="Số luồng tải song song (mặc định: 3)")
    parser.add_argument("--delay", "-d", type=float, default=0.3, help="Thời gian chờ giữa các chương (mặc định: 0.3s)")
    parser.add_argument("--output", "-o", type=str, default="output", help="Thư mục lưu file ZIP (mặc định: output)")
    parser.add_argument("--mode", "-m", type=str, default="individual", choices=["individual", "batch", "both"], help="Chế độ xuất ZIP: individual (mỗi truyện 1 zip), batch (gộp chung 1 zip), both (cả hai)")
    return parser.parse_args()

def main():
    args = parse_args()
    urls: List[str] = []

    if args.url:
        urls.append(args.url.strip())
    elif args.file:
        if not os.path.exists(args.file):
            print(f"[!] Lỗi: File '{args.file}' không tồn tại.")
            sys.exit(1)
        with open(args.file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("http"):
                    urls.append(line)
    else:
        print("=" * 65)
        print("   TOOL CRAWLER TRUYỆN ĐÓNG GÓI ZIP (CHUẨN STORY-TRANSFER)")
        print("=" * 65)
        user_url = input("\nNhập link truyện cần cào: ").strip()
        if not user_url.startswith("http"):
            print("[!] Link không hợp lệ. Vui lòng bắt đầu bằng http:// hoặc https://")
            sys.exit(1)
        urls.append(user_url)

    if not urls:
        print("[!] Không tìm thấy link truyện nào cần cào.")
        sys.exit(1)

    cfg = load_config()
    cleaner = ContentCleaner(custom_phrases=cfg.get("custom_ad_phrases", []))
    zip_builder = ZipBuilder()

    os.makedirs(args.output, exist_ok=True)
    crawler = StoryCrawler(
        cleaner=cleaner,
        zip_builder=zip_builder,
        output_dir=args.output
    )

    create_individual = args.mode in ("individual", "both")
    create_batch = args.mode in ("batch", "both")
    stories_bundle: List[Tuple[StoryInfo, List[ChapterContent]]] = []

    print(f"\n[*] Bắt đầu xử lý {len(urls)} truyện. Thư mục xuất: '{os.path.abspath(args.output)}'\n")

    for idx, url in enumerate(urls, start=1):
        print(f"\n------------------------------------------------------------")
        print(f"[{idx}/{len(urls)}] Đang cào truyện: {url}")
        print(f"------------------------------------------------------------")

        def on_progress(p):
            pct = p.get("percentage", 0)
            msg = p.get("message", "")
            print(f"\r[{pct:>5.1f}%] {msg:<60}", end="", flush=True)

        try:
            res = crawler.crawl_story(
                url=url,
                start_chapter=args.start,
                end_chapter=args.end,
                max_workers=args.workers,
                request_delay=args.delay,
                progress_callback=on_progress,
                create_individual_zip=create_individual
            )
            print(f"\n[✓] {res.get('message')}")
            if res.get("file_path"):
                print(f"    -> Đường dẫn file ZIP: {res.get('file_path')}")
            s_info = res.get("story_info")
            s_chaps = res.get("chapters")
            if s_info and s_chaps:
                stories_bundle.append((s_info, s_chaps))
        except Exception as e:
            print(f"\n[✗] Thất bại khi cào {url}: {e}")

    if create_batch and stories_bundle:
        try:
            batch_path = zip_builder.build_batch_zip(stories_bundle, output_dir=args.output)
            print(f"\n[✓] Đã đóng gói gộp {len(stories_bundle)} truyện vào file ZIP: {batch_path}")
        except Exception as e:
            print(f"\n[✗] Lỗi khi tạo file ZIP gộp: {e}")

    print("\n[+] Hoàn tất toàn bộ danh sách truyện!\n")

if __name__ == "__main__":
    main()
