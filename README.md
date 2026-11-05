# 📦 Story-Transfer ZIP Crawler Pro (Tool Cào Truyện Đóng Gói ZIP Import Website)

Công cụ chuyên dụng giúp **cào toàn bộ nội dung các chương truyện** từ nhiều website khác nhau, **tự động lọc sạch quảng cáo / mã Ad-Inserter / watermark**, và **đóng gói thành file `.zip` theo đúng cấu trúc `story-transfer` v1.0** để import trực tiếp vào website WordPress.

---

## 🌟 Cấu Trúc File ZIP Xuất Ra (`story-transfer`)

Mỗi file `.zip` được tạo tại thư mục `output/` (ví dụ `story-transfer-15789.zip`) có cấu trúc chuẩn 100%:

```
story-transfer-15789.zip
├── manifest.json
└── stories/
    └── story-15789.json
```

- **`manifest.json`**: Chứa thông tin định dạng `"format": "story-transfer"`, `"format_version": "1.0"`, `"plugin_version": "1.4.6"`, `"source_site"`, `"story_count"`, `"fields"`, và danh sách `"stories"`.
- **`stories/story-<id>.json`**:
  - `story`: `uuid`, `original_id`, `title`, `status: "publish"`, `content` (văn bản giới thiệu truyện nhiều đoạn).
  - `chapters`: Danh sách toàn bộ các chương (`original_id`, `number`, `title`, `slug`, `status: "publish"`, `date`, `content` dạng HTML `<p>...</p>` đã lọc sạch quảng cáo, `meta: {"_chapter_number": [...]}`).

---

## 🚀 Hướng Dẫn Sử Dụng

### Cách 1: Giao Diện Web (Khuyên dùng)
1. Nhấp đúp vào file **`Chay_Tool_Web.bat`**.
2. Trình duyệt tự động mở tại `http://localhost:8000`.
3. Dán danh sách link truyện (mỗi dòng 1 link) và chọn chế độ đóng gói ZIP:
   - **Mỗi truyện 1 file ZIP riêng** (`story-transfer-<id>.zip`)
   - **Gộp tất cả vào 1 file ZIP duy nhất** (`story-transfer-batch-*.zip`)
   - **Xuất cả ZIP lẻ và ZIP gộp**
4. Nhấn **"Bắt Đầu Cào & Đóng Gói ZIP"**.

### Cách 2: Dòng Lệnh (CLI)
```bash
# Cào 1 truyện ra file ZIP:
python cli.py --url "https://thaonguyen1.giangsonnhuhoa.com/truyen/2311/"

# Cào giới hạn chương (ví dụ từ chương 1 đến 11):
python cli.py --url "https://thaonguyen.giangsonnhuhoa.com/truyen/1600/" --start 1 --end 11

# Cào nhiều link từ file text và gộp chung vào 1 file ZIP:
python cli.py --file links.txt --mode batch
```
