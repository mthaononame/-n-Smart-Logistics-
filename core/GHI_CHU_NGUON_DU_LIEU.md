# Ghi chú nguồn dữ liệu - ma trận đường đi (Thành viên 4)

_Tự sinh bởi `build_travel_matrix.py` lúc **2026-10-24T23:58:54+07:00** (giờ Việt Nam). Không sửa tay - hãy chạy lại script để cập nhật._

> ⚠️ **ĐÂY LÀ DỮ LIỆU ƯỚC LƯỢNG, KHÔNG PHẢI DỮ LIỆU THEO MẠNG ĐƯỜNG.**
> Khoảng cách = đường chim bay (Haversine) × hệ số đường vòng **1.35**; thời gian = khoảng cách ÷ tốc độ trung bình giả định **25.0 km/h**.
> Hai tham số này là **giả định, chưa được hiệu chỉnh** bằng dữ liệu thực. Chỉ dùng để lập trình/kiểm thử luồng dữ liệu. Trước khi đánh giá chính thức hãy chạy `python build_travel_matrix.py --provider osrm`.

## 1. Tóm tắt lần lấy dữ liệu

| Mục | Giá trị |
|---|---|
| Nguồn | Ước lượng offline (Haversine × hệ số đường vòng) |
| Thời điểm lấy | 2026-10-24T23:58:54+07:00 (UTC: 2026-10-24T16:58:54+00:00) |
| Số địa điểm | 12 (2 kho + 10 điểm giao) |
| Số cặp có hướng (A≠B) | 132 |
| Phương tiện | Ô tô (OSRM profile `driving` / Google `DRIVE`) - **không** xét quy định cấm tải, giờ cấm, tải trọng xe |
| Tham số giả định | hệ số đường vòng = 1.35, tốc độ = 25.0 km/h |
| Giao thông | Không xét |

## 2. Điều kiện sử dụng / bản quyền

- Không dùng dữ liệu bên thứ ba (chỉ dùng toạ độ của dự án) nên không có ràng buộc bản quyền, nhưng cũng **không có giá trị như dữ liệu đường thực**.

## 3. Giới hạn cần nhớ khi diễn giải

- Thời gian là **ước tính di chuyển**, không phải thời gian xe chạy thực tế (không có ùn tắc theo giờ, đèn đỏ, cấm tải, đỗ xe, tìm cổng giao hàng).
- Thời gian **chưa gồm** thời gian dỡ hàng (`thoi_gian_phuc_vu_phut` trong `orders.csv`) - TV2 cộng riêng.
- Ma trận **bất đối xứng**; đường chéo = 0 và không có trong `travel_matrix.csv`.
- Kết quả đã làm tròn về số nguyên: mét và giây.

## 4. Kiểm tra chất lượng tự động

- Khoảng cách: min 3.027 / TB 11.075 / max 25.121 km
- Thời gian: min 7.27 / TB 26.58 / max 60.28 phút; tốc độ trung bình ngầm định ≈ 25.0 km/h
- Hệ số đường-thực/chim-bay: min 1.35 / TB 1.35 / max 1.35
- Bất đối xứng lớn nhất giữa A→B và B→A: 0.0%
- Số bộ ba vi phạm bất đẳng thức tam giác về thời gian (thông tin): 0
- Không có cảnh báo.

## 5. Cách sử dụng (TV2)

```python
from travel_lookup import TravelMatrix
tm = TravelMatrix.from_csv()                    # đọc output/travel_matrix.csv + locations.csv
tm.dist_km('K01', 'D02'); tm.time_min('K01', 'D02')
tot = tm.route_totals(['K01', 'D02', 'D03', 'K01'])   # tổng km + phút di chuyển của 1 tuyến
dist = tm.distance_matrix_m().tolist()          # mét (int)  -> OR-Tools arc cost
time = tm.time_matrix_s().tolist()              # giây (int) -> OR-Tools Time Dimension
# chỉ số node = vị trí trong tm.ids (kho trước, điểm giao sau)
```

Cột của `travel_matrix.csv`: `ma_di, ma_den, khoang_cach_m, thoi_gian_s, khoang_cach_km, thoi_gian_phut, nguon`.

## 6. Tính tái lập

| File đầu vào | SHA-256 |
|---|---|
| depots.csv | `780f0a12596f9229…` |
| orders.csv | `22f74c29307479b0…` |

