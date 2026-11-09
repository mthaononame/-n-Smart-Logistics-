# DATA_GUIDE – Hướng dẫn dữ liệu dự án

Tài liệu do TV1 (phụ trách dữ liệu) bảo trì. Giải thích chi tiết từng cột nằm trong `giai_thich_cot.csv`; tài liệu này hướng dẫn cách dùng, cách thêm dữ liệu, các kịch bản và chương trình kiểm tra.

## 1. Cấu trúc thư mục

```
depots.csv, vehicles.csv, orders.csv, giai_thich_cot.csv   # dữ liệu gốc (KHÔNG ghi đè)
validate_data.py                                            # chương trình kiểm tra dữ liệu
generate_scenarios.py                                       # sinh lại S01–S05 (seed cố định)
validation_report.csv                                       # báo cáo do validate_data.py xuất ra
data/scenarios/
    scenario_description.csv                                # mô tả mục đích / kết quả mong đợi
    S01/ S02/ S03/ S04/ S05/                                # mỗi thư mục có depots, vehicles, orders
tests/test_validate_data.py                                 # kiểm thử cho validator
```

## 2. Quy ước chung (áp dụng cho mọi file CSV)

- Mã hoá **UTF-8 có BOM**. Đọc bằng pandas: `pd.read_csv(path, encoding="utf-8-sig")`.
- Dấu thập phân là **dấu chấm**. Giờ định dạng **HH:MM** (24 giờ).
- Đơn vị: khối lượng **kg**, thể tích **m³**, thời gian **phút**, chi phí **VND**.
- `vi_do`, `kinh_do` là 2 cột riêng, độ thập phân WGS84. `dia_chi` giữ dạng chữ; địa chỉ có dấu phẩy phải đặt trong dấu nháy kép.
- Mã: kho `K01, K02…`, xe `V01, V02…`, đơn `D01, D02…` (một đơn = một điểm giao). Mã phải duy nhất trong từng file.
- `kho_phuc_vu` liệt kê các kho được phép phục vụ đơn, ngăn cách bằng `;` (ví dụ `K01;K02`).
- **Không đổi tên cột.** Các module của nhóm đọc theo tên cột hiện tại.

## 3. Ý nghĩa các cột

### depots.csv
| Cột | Ý nghĩa |
|---|---|
| ma_kho | Mã kho (khoá chính) |
| ten_kho | Tên điểm kho (địa điểm công khai, không phải kho đã hợp tác thật) |
| dia_chi | Địa chỉ kho |
| vi_do, kinh_do | Toạ độ kho |

### vehicles.csv
| Cột | Ý nghĩa |
|---|---|
| ma_xe | Mã xe (khoá chính) |
| ma_kho_quan_ly | Kho quản lý, cũng là kho xuất phát (→ depots.ma_kho) |
| tai_trong_kg, the_tich_m3 | Giới hạn tải trọng và thể tích thùng hàng. **Cả hai** giới hạn đều phải thoả |
| gio_bat_dau_ca, gio_ket_thuc_ca | Ca làm việc; xe phải về trong ca |
| chi_phi_vnd_km | Chi phí theo quãng đường (giả định thử nghiệm) |
| chi_phi_co_dinh_vnd | Chi phí cố định 1 lần/ca khi xe giao ít nhất 1 đơn (giả định thử nghiệm) |

### orders.csv
| Cột | Ý nghĩa |
|---|---|
| ma_don | Mã đơn (khoá chính) |
| ten_khach_hang, dia_chi | Tên địa điểm giao và quận/khu vực |
| vi_do, kinh_do | Toạ độ điểm giao |
| khoi_luong_kg, the_tich_m3 | Khối lượng và thể tích lô hàng |
| thoi_gian_phuc_vu_phut | Thời gian dỡ hàng, tính vào hạn giao |
| gio_bat_dau | Giờ sớm nhất được bắt đầu dỡ (đến sớm phải chờ) |
| gio_ket_thuc | Hạn chót phải **dỡ xong** (không chỉ là giờ xe đến) |
| kho_phuc_vu | Các kho được phép phục vụ đơn |

### Dữ liệu thật và dữ liệu mô phỏng
- **Thực (công khai):** tên, địa chỉ, toạ độ của 2 kho và các điểm giao.
- **Mô phỏng (giả định để thử nghiệm):** khối lượng, thể tích, thời gian dỡ, hạn giao, đội xe, chi phí, `kho_phuc_vu`.
- Toạ độ D01–D10 và 2 kho là bản gốc. **Toạ độ D11–D28 là toạ độ xấp xỉ của địa điểm công khai, cần TV4 xác minh trên bản đồ** trước khi dùng cho kết quả báo cáo.

## 4. Các kịch bản (`data/scenarios/`)

| Mã | Tên | Đơn | Xe | Đặc điểm chính | Kết quả mong đợi |
|---|---|---|---|---|---|
| S01 | Bình thường | 25 | 4 | D01–D10 giữ nguyên bản gốc; 2 cặp đơn cùng địa điểm (D03/D24, D02/D25); 3 đơn nhẹ nhưng cồng kềnh (D14, D20, D23) | Giao đủ 25 đơn, không trễ |
| S02 | Nhu cầu cao | 28 | 6 | Tổng 13.200 kg, vượt năng lực 5 xe | Giao đủ, cần dùng đủ 6 xe |
| S03 | Hạn giao gấp | 25 | 4 | Khung giờ hẹp, dồn 08:30–11:30 | Cần nhiều xe chạy song song, chi phí cao hơn S01 |
| S04 | Giới hạn kho | 24 | 4 | 8 đơn chỉ K01, 8 đơn chỉ K02, 8 đơn cả hai | Không đơn nào gán sai kho |
| S05 | Thiếu năng lực | 26 | 4 | Tổng 12.879 kg > 10.000 kg; D26 nặng 2.900 kg > tải mọi xe; nhiều đơn cồng kềnh | **Không thể giao hết**, phải cảnh báo danh sách đơn chưa phục vụ (chắc chắn có D26) |

Số liệu chi tiết (tổng khối lượng, thể tích, kết quả mong đợi) có trong `data/scenarios/scenario_description.csv`. Các kịch bản được sinh bằng `python generate_scenarios.py` (seed cố định, chạy lại cho cùng kết quả). Nếu cần chỉnh số liệu, sửa trong script rồi sinh lại, đừng sửa tay từng file.

**Dùng kịch bản trong code** (ví dụ):

```python
import pandas as pd
d = "data/scenarios/S04"
depots   = pd.read_csv(f"{d}/depots.csv",   encoding="utf-8-sig")
vehicles = pd.read_csv(f"{d}/vehicles.csv", encoding="utf-8-sig")
orders   = pd.read_csv(f"{d}/orders.csv",   encoding="utf-8-sig")
orders["kho_phuc_vu"] = orders["kho_phuc_vu"].str.split(";")
```

## 5. Chương trình kiểm tra `validate_data.py`

```
python validate_data.py                       # tự tìm thư mục gốc, data/, data/scenarios/*
python validate_data.py data/scenarios/S03    # một thư mục cụ thể
python validate_data.py --strict              # WARNING cũng làm mã thoát = 1
python validate_data.py --quiet               # chỉ in ERROR và tổng kết
```

Mã thoát: `0` không có ERROR, `1` có ERROR, `2` không tìm thấy dữ liệu. Chương trình **không sửa, không xoá, không bỏ qua** dòng lỗi; mỗi lỗi ghi rõ file, dòng (dòng 1 là tiêu đề), cột và nguyên nhân, đồng thời được xuất ra `validation_report.csv` (các cột: `kich_ban, muc_do, file, dong, cot, ma_loi, noi_dung`).

### Ba mức thông báo – phân biệt lỗi dữ liệu và "không có phương án khả thi"

| Mức | Ý nghĩa | Ví dụ mã |
|---|---|---|
| **ERROR** | Dữ liệu **sai**, phải sửa trước khi chạy thuật toán | `E_DUP_ID`, `E_EMPTY`, `E_NOT_NUMBER`, `E_COORD_RANGE`, `E_NON_POSITIVE`, `E_TIME_FORMAT`, `E_TIME_ORDER`, `E_REF_DEPOT`, `E_COLUMN_MISSING`, `E_FIELD_COUNT` |
| **WARNING** | Dữ liệu **hợp lệ** nhưng đáng chú ý hoặc có thể không giao hết được | `W_FEAS_ORDER_TOO_HEAVY`, `W_FEAS_ORDER_TOO_BULKY`, `W_FEAS_FLEET_WEIGHT`, `W_FEAS_FLEET_VOLUME`, `W_FEAS_TIME`, `W_WINDOW_TOO_SHORT`, `W_COORD_OUTSIDE_HCM`, `W_NO_BOM`, `W_ID_FORMAT` |
| **INFO** | Ghi chú, không cần sửa | `I_SAME_LOCATION` (nhiều đơn cùng địa điểm, được phép) |

- S05 là ví dụ điển hình: **0 ERROR**, có WARNING `W_FEAS_*`. Đây là dữ liệu đúng, chỉ là năng lực vận chuyển không đủ.
- Các cảnh báo `W_FEAS_FLEET_*` giả định mỗi xe chạy **một chuyến**. Nếu thuật toán cho phép xe chạy nhiều chuyến trong ca thì cảnh báo này chỉ mang tính tham khảo.
- `W_FEAS_TIME` dùng ước lượng thô (đường chim bay × 1,3, 30 km/h) để tránh phụ thuộc ma trận đường đi; con số có thể chỉnh ở đầu `validate_data.py`.
- Validator cũng đối chiếu danh sách cột với `giai_thich_cot.csv` (nếu tìm thấy) để phát hiện tài liệu lệch với dữ liệu.

Kiểm thử validator: `python -m unittest tests.test_validate_data -v`.

## 6. Cách thêm dữ liệu

**Thêm đơn:** thêm một dòng vào `orders.csv` với mã mới liên tục (ví dụ `D26`), đủ 11 cột. Nhiều đơn có thể cùng toạ độ nhưng phải khác `ma_don`. Đảm bảo `gio_bat_dau + thoi_gian_phuc_vu_phut <= gio_ket_thuc` và `kho_phuc_vu` chỉ chứa mã kho có trong `depots.csv`.

**Thêm xe:** thêm dòng vào `vehicles.csv` với mã mới (`V05`…) và `ma_kho_quan_ly` là kho đã có.

**Thêm kho:** thêm dòng vào `depots.csv` (mã mới `K03`…). Sau đó mới thêm xe thuộc kho đó, và cập nhật `kho_phuc_vu` của các đơn nếu muốn kho mới phục vụ.

**Sau mỗi thay đổi:**
1. Chạy `python validate_data.py` và sửa hết ERROR.
2. Nếu thêm hoặc đổi vị trí (kho hay điểm giao), **báo TV4** để cập nhật ma trận đường đi.
3. Nếu thêm hoặc đổi tên cột, cập nhật `giai_thich_cot.csv` và báo cả nhóm trước, tránh làm hỏng code của TV2/TV3.

## 7. Phối hợp

| Thành viên | Việc cần từ TV1 |
|---|---|
| TV2 | Dữ liệu và kịch bản để chạy thuật toán; hỗ trợ lỗi đầu vào |
| TV3 | Đọc và hiển thị dữ liệu trên giao diện; S05 dùng để thử hiển thị cảnh báo |
| TV4 | Xác minh toạ độ D11–D28 và 2 kho; báo khi đổi vị trí để cập nhật ma trận đường đi (`travel_matrix.csv` đã bị xoá khỏi repo, cần tạo lại cho từng kịch bản) |
| TV5 | Bộ kịch bản, cột `ket_qua_mong_doi` trong `scenario_description.csv`, và `validation_report.csv` để kiểm thử hệ thống |

## 8. Checklist bàn giao

- [ ] `python validate_data.py` cho ERROR = 0 ở mọi thư mục
- [ ] `validation_report.csv` được tạo lại sau lần chạy cuối
- [ ] TV4 đã xác minh toạ độ D11–D28 và cập nhật ma trận đường đi
- [ ] Đã commit đủ `data/scenarios/`, `scenario_description.csv`, `validate_data.py`, `DATA_GUIDE.md`
