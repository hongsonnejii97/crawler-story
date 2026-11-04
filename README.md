# 📖 Story Novel Crawler To Word (Tool Cào Truyện Xuất File Word Pro)

Một công cụ chuyên dụng mạnh mẽ giúp bạn **cào toàn bộ nội dung các chương truyện** từ nhiều website khác nhau, **tự động lọc sạch quảng cáo / watermark**, và **tổng hợp trọn bộ 100% nội dung (không tóm tắt) vào duy nhất 1 file Microsoft Word (`.docx`)**.

---

## 🌟 Tính Năng Nổi Bật

1. **Cào Hàng Loạt (Batch Multi-URLs)**:
   - Dán cùng lúc nhiều link truyện khác nhau (mỗi dòng 1 link) hoặc nhập từ file `.txt`.
   - Tool tự động xử lý tuần tự từng truyện vào từng file Word riêng biệt.

2. **Giữ Nguyên 100% Nội Dung (Không Tóm Tắt)**:
   - Giữ nguyên vẹn toàn bộ câu từ, từng đoạn hội thoại, lời kể của tác giả.
   - Định dạng chuẩn sách in: font chữ Times New Roman 12pt, căn lề 2 bên (Justified), khoảng cách đoạn 6pt, thụt đầu dòng 0.35 inch.

3. **Bộ Lọc Quảng Cáo & Watermark Siêu Sạch**:
   - **Xóa mã quảng cáo HTML**: Loại bỏ hoàn toàn các thẻ `<script>`, `<ins class="adsbygoogle">`, `<iframe>`, khối banner, nút điều hướng, khung tài trợ xen kẽ giữa các đoạn.
   - **Lọc câu watermark / spam text**: Tự động nhận diện và loại bỏ các câu chèn vào nội dung như *"Đọc truyện tại..."*, *"Ủng hộ dịch giả qua STK / Momo"*, *"Tham gia nhóm Zalo / Telegram"*, *"Chúc bạn đọc truyện vui vẻ"*, link website...
   - **Tùy biến bộ lọc**: Có thể thêm/bớt từ khóa quảng cáo theo ý muốn ngay trên giao diện Web.

4. **Trang Bìa & Mục Lục Tự Động**:
   - **Trang bìa**: Tiêu đề truyện lớn in đậm, tên tác giả, nguồn link, tổng số chương, ngày cào, phần tóm tắt giới thiệu truyện.
   - **Mục lục**: Danh sách tất cả các chương được đánh số thứ tự rõ ràng.
   - **Ngắt trang tự động**: Mỗi chương được ngắt sang trang mới riêng biệt như sách xuất bản thật.

5. **Hỗ Trợ Đa Website & Cơ Chế Thích Ứng Thông Minh**:
   - Tối ưu sẵn cho các trang truyện lớn: `TruyenFull`, `WeTruyen`, `DTruyen`, `SSTruyen`, `TangThuVien`...
   - Tích hợp **Universal Auto-Extractor (Bóc tách thông minh)**: Tự động phân tích cấu trúc DOM, nhận diện danh sách chương và nội dung chính trên hầu hết các website truyện khác.
   - Công nghệ **`curl_cffi` (Chrome TLS Impersonation)** giúp vượt qua các tường lửa chống bot và Cloudflare của các web truyện.

6. **Đa Dạng Giao Diện**:
   - **Giao diện Web hiện đại**: Trực quan, thanh tiến độ % thời gian thực, bảng nhật ký live, tải file Word trực tiếp trên trình duyệt.
   - **Giao diện Dòng lệnh (CLI)**: Dành cho người thích chạy dòng lệnh hoặc tích hợp tự động hóa.

---

## 🚀 Hướng Dẫn Sử Dụng Nhanh (Windows)

### Cách 1: Sử dụng Giao Diện Web (Khuyên dùng)
1. Nhấp đúp vào file **`Chay_Tool_Web.bat`**.
2. Trình duyệt web sẽ tự động mở trang điều khiển tại địa chỉ: `http://localhost:8000`.
3. Dán danh sách các link truyện vào ô nhập (mỗi dòng 1 link).
4. Nhấn **"Bắt Đầu Cào Truyện & Xuất Word"**.
5. Theo dõi tiến độ trực tiếp. Khi hoàn tất, bạn có thể bấm **"Tải Word"** hoặc bấm **"Mở Thư Mục Trên Máy Tính"** để lấy file.

### Cách 2: Sử dụng Dòng Lệnh (CLI)
Nhấp đúp vào file **`Chay_Tool_CLI.bat`** hoặc mở terminal và chạy:

```bash
# Cào 1 truyện cụ thể:
python cli.py --url "https://wetruyen.com/bat-ai-thanh-hon.1381/"

# Cào truyện với giới hạn số chương (ví dụ từ chương 1 đến 50):
python cli.py --url "https://wetruyen.com/bat-ai-thanh-hon.1381/" --start 1 --end 50

# Cào hàng loạt từ file text:
python cli.py --file danh_sach_link.txt --workers 3
```

---

## 📁 Cấu Trúc Dự Án

```
Crawler/
├── app.py                      # Máy chủ FastAPI & Web API
├── cli.py                      # Trình cào truyện qua dòng lệnh (CLI)
├── config.json                 # Cấu hình bộ lọc quảng cáo & thông số
├── requirements.txt            # Danh sách thư viện Python
├── Chay_Tool_Web.bat           # 1-Click khởi chạy Web UI
├── Chay_Tool_CLI.bat           # 1-Click chạy dòng lệnh
├── core/
│   ├── fetcher.py              # Bộ tải trang chống chặn bot (curl_cffi)
│   ├── cleaner.py              # Bộ lọc sạch quảng cáo & watermark
│   ├── doc_builder.py          # Bộ tạo file Word (.docx) chuyên nghiệp
│   ├── crawler.py              # Bộ điều phối cào & đa luồng
│   ├── config_manager.py       # Quản lý cài đặt
│   └── site_handlers/          # Bộ bóc tách theo từng trang & thông minh
│       ├── base.py
│       ├── wetruyen_truyenfull.py
│       └── universal.py
├── web/
│   └── index.html              # Giao diện Web hiện đại, responsive
└── output/                     # Thư mục chứa các file Word đã cào
```

---

## ⚙️ Tùy Chỉnh Nâng Cao

- **Số luồng tải song song (Concurrency)**: Mặc định là `3` luồng. Có thể tăng lên `5` hoặc `8` để tăng tốc độ cào.
- **Thời gian chờ (Delay)**: Mặc định `0.3s` giữa các chương để tôn trọng máy chủ nguồn và tránh bị chặn IP.
- **Thư mục xuất file**: Mặc định lưu tại thư mục `output/`.

