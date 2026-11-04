"""
Command-Line Interface (CLI) for Story Novel Crawler.
Allows running single or batch crawling directly from the terminal.
"""
import os
import sys
import argparse
from typing import List

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from core.crawler import StoryCrawler
from core.cleaner import ContentCleaner
from core.doc_builder import DocBuilder
from core.config_manager import load_config

def parse_args():
    parser = argparse.ArgumentParser(description="Tool Crawler Truyện Xuất Word Không Tóm Tắt & Lọc Quảng Cáo")
    parser.add_argument("--url", "-u", type=str, help="Link truyện cần cào (ví dụ: https://wetruyen.com/bat-ai-thanh-hon.1381/)")
    parser.add_argument("--file", "-f", type=str, help="File text chứa danh sách link (mỗi dòng 1 link)")
    parser.add_argument("--start", "-s", type=int, default=1, help="Chương bắt đầu (mặc định: 1)")
    parser.add_argument("--end", "-e", type=int, default=None, help="Chương kết thúc (mặc định: hết truyện)")
    parser.add_argument("--workers", "-w", type=int, default=3, help="Số luồng tải song song (mặc định: 3)")
    parser.add_argument("--delay", "-d", type=float, default=0.3, help="Thời gian chờ giữa các chương (mặc định: 0.3s)")
    parser.add_argument("--output", "-o", type=str, default="output", help="Thư mục lưu file Word (mặc định: output)")
    parser.add_argument("--font", type=str, default="Times New Roman", help="Font chữ trong file Word")
    parser.add_argument("--no-toc", action="store_true", help="Không tạo trang Mục lục")
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
        # Interactive prompt if no args provided
        print("="*60)
        print("   TOOL CRAWLER TRUYỆN XUẤT 1 FILE WORD (KHÔNG TÓM TẮT)")
        print("="*60)
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
    doc_builder = DocBuilder(font_name=args.font, font_size=12)

    os.makedirs(args.output, exist_ok=True)
    crawler = StoryCrawler(
        cleaner=cleaner,
        doc_builder=doc_builder,
        output_dir=args.output
    )

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
                progress_callback=on_progress
            )
            print(f"\n[✓] {res.get('message')}")
            print(f"    -> Đường dẫn file: {res.get('file_path')}")
        except Exception as e:
            print(f"\n[✗] Thất bại khi cào {url}: {e}")

    print("\n[+] Hoàn tất toàn bộ danh sách truyện!\n")

if __name__ == "__main__":
    main()

