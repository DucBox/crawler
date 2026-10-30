# crawler — Phase 2: keyword → URL ảnh (Bing Images)

Đầu vào là **một file txt, mỗi dòng một keyword** (tên người). Với mỗi keyword, script lấy khoảng 100 URL ảnh gốc từ Bing Images và ghi ra file TSV. Có thêm script tuỳ chọn để tải ảnh từ các URL đó.

Phase 1 (tạo danh sách tên từ Wikidata) không nằm trong repo này.

## Cài đặt

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Chạy

```bash
# 1. Lấy URL
python crawl_urls.py input/keywords.txt -o output/urls.tsv --workers 4 --delay 1.0

# 2. (tuỳ chọn) Tải ảnh, giữ 50 ảnh hợp lệ đầu tiên của mỗi keyword
python download_images.py output/urls.tsv -o images -n 50
```

Thử nhanh: `python crawl_urls.py input/keywords.example.txt --limit 3`

### Tham số `crawl_urls.py`

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `-o, --output` | `output/urls.tsv` | file kết quả |
| `--urls` | 100 | số URL mỗi keyword (mỗi page Bing tối đa 35 URL → 100 URL ≈ 3 request) |
| `--workers` | 4 | số luồng chạy song song |
| `--delay` | 1.0 | số giây chờ sau mỗi request, tính riêng từng luồng |
| `--proxy` | — | `http://user:pass@host:port`, dùng được nhiều lần |
| `--proxy-file` | — | file proxy, mỗi dòng một proxy (dòng bắt đầu bằng `#` bị bỏ qua) |
| `--cooldown` | 900 | số giây nghỉ khi nghi bị chặn (tăng gấp đôi nếu vẫn bị, tối đa 4 giờ) |
| `--empty-limit` | 8 | số page đầu rỗng liên tiếp bị coi là dấu hiệu bị chặn |
| `--limit` | — | chỉ crawl N keyword đầu |

Proxy lấy từ `--proxy`, rồi `--proxy-file`, và nếu không có thì từ biến môi trường `PROXY_URL` (xem `.env.example`). Luồng thứ `i` dùng proxy thứ `i % số proxy`. Không có proxy thì request đi thẳng từ IP của máy.

## Định dạng

**Input** — `input/keywords.txt`:

```
messi
Nguyễn Thị Kim Ngân
Vũ nhôm
```

Dòng trống và keyword trùng bị bỏ qua. Nên lưu UTF-8.

**Output** — `output/urls.tsv` (cách nhau bằng tab, `rank` là thứ hạng trong kết quả Bing, 1 là đầu tiên):

```
url	keyword	rank
https://example.com/a.jpg	messi	1
```

Các file đi kèm:
- `output/urls.tsv.done` — keyword đã xong. **Chạy lại cùng lệnh sẽ bỏ qua các keyword này**, nên ngắt giữa chừng rồi chạy tiếp được.
- `output/urls.tsv.failed` — keyword không ra URL nào (hoặc lỗi mạng); không nằm trong `.done` nên lần sau sẽ được thử lại.

**Ảnh** — `images/<keyword>_<hash>/<rank>.<ext>` và `images/manifest.tsv` (`folder, file, keyword, rank, url`). Ảnh hợp lệ là ảnh mở được bằng Pillow, cạnh ngắn ≥ 100px, không trùng nội dung.

## Số đo đã thực hiện

Đo trên **một IP proxy datacenter**, khoảng 1 giờ, 4 luồng, delay 1 giây:

- Tốc độ khoảng **2,2–2,9 request/giây**, thời gian phản hồi trung bình 0,4–0,95 giây.
- Chưa gặp 429/403 hay trang chặn nào trong khoảng thời gian đó.
- 3 page mỗi keyword: trung bình khoảng 103 URL, ít nhất 72, nhiều nhất 109 (mẫu 644 tên ngẫu nhiên từ Wikidata). Khoảng 14% keyword dưới 100 URL.
- Khoảng 90–96% URL tải được; phần còn lại là link chết hoặc site chặn tải (402/403).

Các con số này chỉ là kết quả của một lần thử ngắn. Chưa biết Bing có chặn khi chạy nhiều giờ liền hay không, và ngưỡng bị chặn của từng IP.

## Lưu ý

- Script dùng endpoint không chính thức của Bing (`/images/async`). Bing có thể đổi cấu trúc bất cứ lúc nào; khi đó `parse_page` trong `crawl_urls.py` là chỗ cần sửa. Chạy `python -m unittest discover -s tests` để kiểm tra phần parse.
- Khi bị chặn (429/403/503 hoặc nhiều page rỗng liên tiếp), luồng đó nghỉ `--cooldown` giây rồi thử lại. Không có cơ chế tự đổi sang proxy khác.
- Kết quả tìm theo tên **không bảo đảm đúng người** (có thể lẫn ảnh poster, ảnh nhiều người, người trùng tên). Repo này không lọc nội dung ảnh.
- Ảnh trên web có bản quyền và có thể chứa dữ liệu cá nhân; hãy kiểm tra điều khoản của Bing và quyền sử dụng ảnh trước khi dùng ở quy mô lớn.

## Kiểm thử

```bash
python -m unittest discover -s tests -v
```
