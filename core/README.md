# TV4 - Dữ liệu khoảng cách & thời gian theo mạng đường (Smart Logistics MDVRPTW)

Gói này hoàn thành nhiệm vụ **Tuần 2 của Thành viên 4**: biến *danh sách toạ độ kho + điểm giao* thành
**ma trận khoảng cách / thời gian di chuyển theo mạng đường** mà thuật toán (TV2) dùng được ngay.

> ## ⚠️ ĐỌC TRƯỚC
> Các file trong `output/` đi kèm gói này được sinh bằng nguồn **`estimate` (ƯỚC LƯỢNG offline)** vì môi trường
> tạo gói không có internet. Chúng **không phải dữ liệu đường thực** (cột `nguon` = `uoc_luong` ở mọi dòng).
> Để có dữ liệu đường thực, chạy **một lệnh** trên máy có mạng:
>
> ```
> python build_travel_matrix.py --provider osrm
> ```
>
> Lệnh này ghi đè `output/` bằng dữ liệu OpenStreetMap/OSRM (miễn phí, được phép lưu lâu dài).

---

## 1. Bàn giao gì (khớp yêu cầu TV4)

| Yêu cầu | File |
|---|---|
| `travel_matrix.csv` | `output/travel_matrix.csv` (132 dòng = 12 × 11 cặp có hướng) |
| Danh sách địa điểm kèm mã vị trí | `output/locations.csv` (`loc_idx`, `ma_vi_tri` = K01…D10) |
| Ghi chú nguồn, thời điểm/điều kiện lấy, cách dùng | `output/GHI_CHU_NGUON_DU_LIEU.md` (tự sinh theo từng lần chạy) + `output/travel_matrix_meta.json` |
| Bản ma trận vuông mở bằng Excel | `output/matrix_distance_km.csv`, `output/matrix_duration_min.csv` |
| Điều kiện hoàn thành: TV2 tính được một tuyến nhỏ | `demo_small_route.py`, `travel_lookup.py` |

## 2. Cấu trúc thư mục

```
tv4_travel_matrix/
├── build_travel_matrix.py     # script chính (CLI): 3 nguồn dữ liệu, kiểm tra chất lượng, ghi file
├── travel_lookup.py           # thư viện cho TV2: tra cứu, tổng tuyến, xuất ma trận số nguyên cho OR-Tools
├── demo_small_route.py        # minh hoạ: giờ đến/chờ/dỡ/hạn, tải trọng, chi phí của MỘT tuyến cho trước
├── tests/test_travel_matrix.py# 43 bài kiểm thử (không cần mạng, không cần pytest)
├── data/                      # depots.csv, orders.csv, vehicles.csv, giai_thich_cot.csv (bản của TV1)
├── output/                    # kết quả bàn giao
├── requirements.txt
└── README.md
```

## 3. Cài đặt và chạy (Windows)

```bat
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

:: 1) Chạy kiểm thử (không cần mạng)
python -m unittest discover -s tests -v

:: 2) Sinh dữ liệu ĐƯỜNG THỰC từ OpenStreetMap (cần mạng, miễn phí) -> output/
python build_travel_matrix.py --provider osrm

:: 3) Thử một tuyến nhỏ
python travel_lookup.py K01 D02 D03 K01
python demo_small_route.py --vehicle V01 --route D02,D08,D10 --depart 06:50
```

Các chế độ khác:

```bat
:: Chưa có mạng, cần dữ liệu tạm để lập trình (ƯỚC LƯỢNG - có cảnh báo ở mọi nơi)
python build_travel_matrix.py --provider estimate

:: Chỉ lấy nhóm nhỏ 2 kho + 3 điểm giao (bước 5), hoặc tự chọn mã
python build_travel_matrix.py --provider osrm --small-test --out output_small
python build_travel_matrix.py --provider osrm --only K01,K02,D01,D02,D03 --out output_small

:: OSRM lỗi mạng thì tự chuyển sang ước lượng (vẫn đánh dấu rõ là ước lượng)
python build_travel_matrix.py --provider osrm --fallback-estimate

:: Google (cần khoá API + thanh toán; chỉ để thử/đối chiếu - xem mục 5)
set GOOGLE_MAPS_API_KEY=khoa_cua_ban            &:: PowerShell: $env:GOOGLE_MAPS_API_KEY="khoa_cua_ban"
python build_travel_matrix.py --provider google --small-test
```

Mã thoát: `0` thành công · `2` dữ liệu/tham số sai hoặc bị chặn an toàn · `3` lỗi nguồn dữ liệu (mạng, API key…).

## 4. Đối chiếu với 7 bước của TV4

| Bước | Thực hiện |
|---|---|
| 1. Nhận toạ độ từ TV1 | `data/depots.csv` + `data/orders.csv` → `load_locations()`; kiểm tra mã trùng, toạ độ không phải số, ngoài phạm vi WGS84 (chặn), ngoài khung TP.HCM / trùng toạ độ (cảnh báo), `kho_phuc_vu` & `ma_kho_quan_ly` trỏ tới kho không tồn tại (cảnh báo) |
| 2. Danh sách địa điểm cần tính | 12 địa điểm (2 kho + 10 điểm giao) → 12 × 11 = **132 cặp có hướng**; xe phải về kho nên cần cả chiều đi lẫn về, và ma trận **bất đối xứng** (đường một chiều) |
| 3. Cách Google Routes API tính | Mục 5.1 |
| 4. Tài khoản, thanh toán, hạn mức, điều kiện lưu | Mục 5.2 - 5.4 |
| 5. Thử nhóm nhỏ | `--small-test` (2 kho + 3 điểm giao = 20 cặp = 25 phần tử Google) |
| 6. Bảng đi / đến / khoảng cách / thời gian | `output/travel_matrix.csv` (mục 7) |
| 7. Dữ liệu dự phòng từ nguồn mở, được phép lưu lâu dài | `--provider osrm` (OpenStreetMap, ODbL) - **được chọn làm nguồn chính thức**; `--provider estimate` chỉ để phát triển |

## 5. Kết quả nghiên cứu Google Maps Routes API

*(Tra cứu ngày 24/10/2026. Giá, hạn mức và điều khoản có thể đổi - kiểm tra lại trang chính thức trước khi dùng thật.)*

### 5.1 API tính khoảng cách/thời gian thế nào
- Dùng `POST https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix` với danh sách `origins` × `destinations`.
- Bắt buộc có header `X-Goog-Api-Key` và `X-Goog-FieldMask` (ví dụ `originIndex,destinationIndex,duration,distanceMeters,status,condition`).
- Mỗi **phần tử** (một cặp đi-đến) trả về `distanceMeters`, `duration` (chuỗi dạng `"361s"`) và `condition` (`ROUTE_EXISTS`…).
- Tối đa **625 phần tử/yêu cầu** (không phải TRANSIT) → code tự chia khối 25 × 25.
- Phần tử trả về **không đảm bảo theo thứ tự** → phải ghép theo `originIndex`/`destinationIndex`; và JSON **bỏ trường có giá trị 0** (vd điểm đến chính nó không có `distanceMeters`) → code dùng giá trị mặc định 0. Cả hai đã có bài test.
- `TRAFFIC_UNAWARE` (mặc định của script): không xét giao thông, rẻ nhất. `TRAFFIC_AWARE` (`--traffic-aware`): có giao thông, SKU đắt hơn.

### 5.2 Tài khoản và thanh toán
Cần dự án Google Cloud + **bật thanh toán** + bật Routes API + tạo API key (nên giới hạn key theo API và IP). Script đọc khoá từ biến môi trường `GOOGLE_MAPS_API_KEY` (không nhận qua tham số dòng lệnh để khỏi lộ khoá trong lịch sử lệnh).

### 5.3 Hạn mức/giá (theo bảng giá toàn cầu, tra cứu 24/10/2026)

| SKU | Miễn phí/tháng | Sau đó (mỗi 1.000 phần tử) |
|---|---|---|
| Compute Route Matrix **Essentials** (TRAFFIC_UNAWARE) | 10.000 phần tử | 5 USD |
| Compute Route Matrix **Pro** (TRAFFIC_AWARE) | 5.000 phần tử | 10 USD |

Tính theo **số phần tử** (origins × destinations), không theo số yêu cầu. Dữ liệu của nhóm: 12 × 12 = **144 phần tử** cho cả bộ → nằm gọn trong hạn mức miễn phí; nhưng vẫn phải gắn thẻ thanh toán. Script có chốt chặn `--max-elements` (mặc định 1000) để không lỡ gọi quá tay.

### 5.4 Điều kiện lưu kết quả ⚠️ (quan trọng)
Theo *Google Maps Platform Service Specific Terms* (bản sửa đổi 04/06/2026, em đọc trên trang lưu trữ):
- Mục **Routes API**: chỉ được cache tạm **toạ độ (lat/lng) tối đa 30 ngày**; ID địa điểm (`place_id`) được cache theo điều khoản chung. **Không có ngoại lệ nào cho khoảng cách/thời gian** (khác Navigation Connect có ghi rõ 30 ngày cho distance/duration). Điều khoản chung của nền tảng cấm lưu/cache nội dung Google ngoài các ngoại lệ được liệt kê.
- Không được dùng nội dung của Routes API **cùng với bản đồ không phải của Google**.

**Hệ quả cho dự án (nên trao đổi với nhóm & giảng viên):**
1. Mục *Rủi ro API* trong phiếu đăng ký đề xuất "lưu cục bộ (cache) ma trận khoảng cách sau lần chạy đầu" → với **Google** cách này **không có căn cứ trong điều khoản**. Với **OSRM/OpenStreetMap** thì làm được.
2. Nếu TV3 vẽ bản đồ bằng nền OpenStreetMap/Folium/… thì không được trộn với dữ liệu tuyến lấy từ Google.
3. Vì vậy script đặt kết quả Google ở `output_google/` (đã đưa vào `.gitignore`) và ghi cảnh báo trong ghi chú; **bộ dữ liệu chính thức của nhóm nên là OSRM**. Google dùng được để *đối chiếu ngắn hạn* (so với OSRM trên nhóm nhỏ) rồi xoá.

*(Em không phải luật sư; đây là cách đọc điều khoản để nhóm quyết định, không phải tư vấn pháp lý.)*

### 5.5 Vì sao chọn OSRM làm nguồn chính thức
| | OSRM (OpenStreetMap) | Google Routes API | Ước lượng offline |
|---|---|---|---|
| Chi phí | Miễn phí | Cần thanh toán (144 phần tử nằm trong mức miễn phí) | Miễn phí |
| Theo mạng đường thật | Có (đường một chiều, ngõ cụt…) | Có | **Không** |
| Giao thông | Không | Tuỳ chọn (Pro) | Không |
| Lưu & dùng lâu dài | Được, **ghi nguồn** (ODbL) | **Không** (xem 5.4) | Không ràng buộc |
| Dùng với bản đồ OSM của TV3 | Được | **Không** | Được |
| Ổn định khi chạy | Máy chủ demo công cộng có thể chậm/ngừng; có thể tự dựng bằng Docker | Ổn định | Luôn chạy |

Máy chủ `router.project-osrm.org` là **máy chủ demo**, không dành cho production. Với 12 địa điểm, script chỉ gửi **1 yêu cầu** (và nghỉ ≥ 1 giây giữa các yêu cầu nếu nhiều hơn) nên phù hợp việc học tập. Nếu cần dùng nặng: tự chạy OSRM bằng Docker và đặt `--osrm-url http://localhost:5000`.

Khi công bố/báo cáo ghi: *"Dữ liệu đường: © OpenStreetMap contributors; định tuyến: OSRM."*

## 6. Tham số của nguồn ước lượng (chỉ để phát triển)
`estimate`: khoảng cách = Haversine × **1.35**; thời gian = khoảng cách ÷ **25 km/h**. Hai số này là **giả định, chưa hiệu chỉnh**. Sau khi chạy OSRM, xem `validation.he_so_duong_vong` và `toc_do_tb_kmh` trong `travel_matrix_meta.json` để chỉnh `--circuity` / `--speed-kmh` cho sát hơn nếu cần dữ liệu dự phòng.

## 7. Định dạng file bàn giao

Mã hoá UTF-8 có BOM (mở bằng Excel không lỗi tiếng Việt; pandas: `encoding="utf-8-sig"`), dấu thập phân là dấu chấm - cùng quy ước với `giai_thich_cot.csv`.

**`locations.csv`**: `loc_idx, ma_vi_tri, loai, ten, dia_chi, vi_do, kinh_do` - kho trước, điểm giao sau; `loc_idx` chính là chỉ số hàng/cột của ma trận.

**`travel_matrix.csv`**:

| Cột | Ý nghĩa |
|---|---|
| `ma_di`, `ma_den` | Mã địa điểm đi / đến (K01, D02, …). Chỉ có cặp `ma_di ≠ ma_den`; đường chéo = 0 |
| `khoang_cach_m` | Quãng đường theo đường đi, **mét (số nguyên)** |
| `thoi_gian_s` | Thời gian di chuyển ước tính, **giây (số nguyên)** |
| `khoang_cach_km`, `thoi_gian_phut` | Bản quy đổi để đọc cho tiện (làm tròn 3 / 2 chữ số) |
| `nguon` | `osrm` / `google_routes` / `uoc_luong` - **theo từng dòng** (nếu vài cặp phải điền bằng ước lượng sẽ thấy ngay) |

Lưu ý khi diễn giải: thời gian là **ước tính** (không có ùn tắc theo giờ, đèn đỏ, giờ cấm tải…), **chưa gồm** thời gian dỡ hàng; OSRM profile ô tô / Google `DRIVE` **không xét quy định cấm tải** của xe tải 2,5 tấn - nên kiểm tra thêm quy định thực tế.

## 8. Hướng dẫn cho TV2 (OR-Tools)

```python
from travel_lookup import TravelMatrix
tm = TravelMatrix.from_csv()                       # output/travel_matrix.csv + locations.csv

tm.dist_km("K01", "D02"); tm.time_min("K01", "D02")
tot = tm.route_totals(["K01", "D02", "D03", "K01"])  # .khoang_cach_km, .thoi_gian_di_chuyen_phut, .legs

dist = tm.distance_matrix_m().tolist()             # mét, int  -> chi phí cung (12.000 VND/km = 12 VND/m)
dur  = tm.time_matrix_s().tolist()                 # giây, int -> Time Dimension
node = tm.idx("D05")                               # chỉ số node = vị trí trong tm.ids
```

Gợi ý nối vào bài toán nhiều kho (**minh hoạ cách nối dữ liệu; em chưa chạy với OR-Tools trong môi trường này**):

```python
from ortools.constraint_solver import pywrapcp
starts = [tm.idx(k) for k in ("K01", "K01", "K02", "K02")]      # kho của từng xe (vehicles.csv)
manager = pywrapcp.RoutingIndexManager(tm.n, len(starts), starts, starts)   # xe phải về đúng kho
routing = pywrapcp.RoutingModel(manager)
N = manager.IndexToNode
cost_cb = routing.RegisterTransitCallback(lambda i, j: dist[N(i)][N(j)] * 12)            # VND
time_cb = routing.RegisterTransitCallback(lambda i, j: dur[N(i)][N(j)] + service_s[N(i)])  # đi + dỡ hàng tại điểm đi
# service_s[k] = thoi_gian_phuc_vu_phut * 60 theo thứ tự tm.ids (kho = 0)
# routing.SetFixedCostOfVehicle(800000, v) cho từng xe; time window = [gio_bat_dau, gio_ket_thuc - phục vụ] tính bằng giây
```

Khuyến nghị: dùng **giây** cho Time Dimension (tránh sai lệch do làm tròn phút từng cung - `time_matrix_min()` có sẵn nhưng cộng dồn sẽ lệch).

## 9. Kiểm thử

`python -m unittest discover -s tests -v` → **43 bài**, gồm: Haversine; nạp & kiểm tra dữ liệu đầu vào (mã trùng, thiếu cột, dấu phẩy thập phân, đảo vĩ/kinh độ, nhập sai chữ số); OSRM giả lập (1 yêu cầu, chia khối 16 yêu cầu cho kết quả giống hệt, thử lại 503 với backoff, mất mạng, mã lỗi `TooBig`, cặp `null`, cảnh báo bám đường); Google giả lập (phần tử xáo trộn + bỏ trường 0, chia khối, thiếu tuyến, lỗi 403 không lộ khoá, `departureTime`); kiểm tra chất lượng ma trận; chạy trọn quy trình CLI; bộ chốt chặn (ước lượng không ghi đè dữ liệu thật, vượt `--max-elements`, thiếu khoá); `travel_lookup` (file thiếu cặp/lặp cặp); giờ đến/chờ/hạn/tải/chi phí của `demo_small_route`.

**Chưa được kiểm chứng**: các lệnh gọi **thật** tới OSRM/Google (môi trường tạo gói không có internet nên dùng server giả đúng định dạng tài liệu API). Lần đầu chạy `--provider osrm` trên máy bạn, hãy mở `GHI_CHU_NGUON_DU_LIEU.md` xem mục *Kiểm tra chất lượng* (tốc độ trung bình hợp lý ~15-40 km/h, hệ số đường vòng ~1.1-1.6, không có cảnh báo bám đường).

## 10. Xử lý sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| `LỖI NGUỒN DỮ LIỆU: OSRM: không kết nối được…` | Kiểm tra mạng/tường lửa; thử lại sau; hoặc `--osrm-url` tới máy chủ OSRM khác/tự dựng; tạm dùng `--fallback-estimate` |
| `OSRM trả lỗi … TooBig` | Giảm `--osrm-max-coords` |
| `OSRM … 429` | Tăng `--osrm-pause`, `--backoff`; máy chủ demo đang quá tải |
| `Toạ độ … cách đường gần nhất … m` | Toạ độ nằm sâu trong khuôn viên (chợ, trung tâm thương mại): dời toạ độ ra cổng/đường chính trong `orders.csv` |
| `… đang chứa dữ liệu ĐƯỜNG THỰC … ghi đè` | Chốt chặn: ước lượng không được đè dữ liệu thật; dùng `--out` khác hoặc `--force` |
| Console Windows hiển thị lỗi dấu tiếng Việt | Script tự chuyển stdout sang UTF-8; nếu vẫn lỗi: `chcp 65001` |
| Excel hiện chữ lạ | Mở bằng *Data → From Text/CSV* và chọn UTF-8 (file có BOM thường mở thẳng được) |
