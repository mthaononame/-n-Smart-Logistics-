# BÁO CÁO PHÂN XE BAN ĐẦU VÀ SO SÁNH PHƯƠNG ÁN (TV2)

---

## I. MỞ ĐẦU & NGUYÊN TẮC PHÂN XE (LOGIC THUẬT TOÁN)

Trong giai đoạn phân bổ ban đầu (Baseline Allocation), thuật toán tập trung giải quyết bài toán gom đơn hàng vào phương tiện dựa trên các ràng buộc kỹ thuật cốt lõi. Để đảm bảo tính chính xác và bám sát thực tế vận hành, mã nguồn Python được thiết kế dựa trên các nguyên tắc xử lý nghiêm ngặt sau:

1. **Kiểm tra điều kiện `kho_phuc_vu` bắt buộc**:
   - Trước khi phân bổ, thuật toán truy xuất và kiểm tra cột `kho_phuc_vu` trong tệp `orders.csv`.
   - Đơn hàng chỉ được phép gán cho các xe thuộc quản lý của kho nằm trong danh sách được phép phục vụ. Hệ thống tuyệt đối không tự động gán đơn cho kho gần nhất nếu kho đó không có tên trong cột `kho_phuc_vu`.
2. **Thứ tự ưu tiên theo khoảng cách Haversine**:
   - Đối với các đơn hàng cho phép phục vụ từ nhiều kho (ví dụ: `K01;K02`), hệ thống sẽ tính khoảng cách địa lý từ vị trí đơn hàng tới từng kho cho phép và ưu tiên thử gán vào xe của kho gần nhất trước.
3. **Ràng buộc sức chứa kép (Tải trọng & Thể tích)**:
   - Một đơn hàng chỉ được gán vào xe khi thỏa mãn đồng thời hai điều kiện:
     $$\text{Tải trọng lũy kế} + \text{Tải trọng đơn} \le \text{Tải trọng tối đa của xe } (2.500\text{ kg})$$
     $$\text{Thể tích lũy kế} + \text{Thể tích đơn} \le \text{Thể tích tối đa của xe } (15\text{ m}^3)$$
4. **Cơ chế phát hiện và cảnh báo đơn bị bỏ sót (Fallback Check)**:
   - Nhằm tránh tình trạng bỏ sót đơn hàng do vượt quá sức chứa hoặc không tìm thấy kho hợp lệ, mã nguồn tích hợp bộ lọc bắt ngoại lệ (`unassigned_records`). Nếu đơn không phân bổ được, hệ thống sẽ ghi nhận nguyên nhân chi tiết (ví dụ: vượt tải trọng, vượt thể tích, sai mã kho) và phát cảnh báo trên màn hình điều hành.

---

## II. KẾT QUẢ PHÂN XE BẰNG PYTHON (PHƯƠNG ÁN 1 - BASELINE 3 XE)

Áp dụng quy tắc phân bổ cơ sở (First-Fit Decreasing / Heuristic) cho $10$ đơn hàng thuộc tệp dữ liệu `orders.csv`, hệ thống huy động **3 xe** (`V01`, `V02`, `V03`) xuất phát từ 2 kho (`K01`, `K02`).

### 1. Chi tiết phân bổ từng xe

* **Xe V01 (Thuộc Kho K01 - Phú Nhuận)**:
  - **Đơn hàng đảm nhận ($7$ đơn)**: `D02`, `D03`, `D04`, `D05`, `D07`, `D08`, `D10`.
  - **Khối lượng tích lũy**: $2.323,40\text{ kg} / 2.500\text{ kg}$ $\rightarrow$ Mức sử dụng tải trọng đạt **$92,94\%$**.
  - **Thể tích tích lũy**: $9,82\text{ m}^3 / 15\text{ m}^3$ $\rightarrow$ Mức sử dụng thể tích đạt **$65,47\%$**.

* **Xe V02 (Thuộc Kho K01 - Phú Nhuận)**:
  - **Đơn hàng đảm nhận ($1$ đơn)**: `D09`.
  - **Khối lượng tích lũy**: $580,60\text{ kg} / 2.500\text{ kg}$ $\rightarrow$ Mức sử dụng tải trọng đạt **$23,22\%$**.
  - **Thể tích tích lũy**: $2,07\text{ m}^3 / 15\text{ m}^3$ $\rightarrow$ Mức sử dụng thể tích đạt **$13,80\%$**.

* **Xe V03 (Thuộc Kho K02 - Thủ Đức)**:
  - **Đơn hàng đảm nhận ($2$ đơn)**: `D01`, `D06`.
  - **Khối lượng tích lũy**: $832,70\text{ kg} / 2.500\text{ kg}$ $\rightarrow$ Mức sử dụng tải trọng đạt **$33,31\%$**.
  - **Thể tích tích lũy**: $3,19\text{ m}^3 / 15\text{ m}^3$ $\rightarrow$ Mức sử dụng thể tích đạt **$21,27\%$**.

* **Xe V04 (Thuộc Kho K02 - Thủ Đức)**:
  - **Trạng thái**: Không điều động ($0\text{ kg} / 0\text{ m}^3$).

### 2. Chi phí cố định Phương án 1
With $3$ xe hoạt động, chi phí mở xe cố định là:
$$\text{Chi phí cố định (PA1)} = 3 \text{ xe} \times 800.000\text{ VNĐ/xe} = \mathbf{2.400.000\text{ VNĐ}}$$

---

## III. PHƯƠNG ÁN SO SÁNH (PHƯƠNG ÁN 2 - GOM ĐƠN D09 TẠO MÔ HÌNH 2 XE)

### 1. Đề xuất phương án điều chỉnh
Ở Phương án 1, xe `V02` chỉ đảm nhận duy nhất đơn hàng `D09` ($580,60\text{ kg}$, $2,07\text{ m}^3$), dẫn đến việc xe bị thiếu tải nghiêm trọng (chỉ lấp đầy $23,22\%$).

Theo yêu cầu tối ưu hóa sơ bộ, ta tiến hành thử nghiệm **Phương án 2**: Chuyển đơn `D09` sang xe `V03` của Kho `K02` (do cột `kho_phuc_vu` của đơn `D09` cho phép cả 2 kho `K01;K02`). khi đó xe `V02` được cắt giảm hoàn toàn.

### 2. Kiểm tra khả năng đáp ứng của Xe V03
Sau khi tiếp nhận thêm đơn `D09`, chỉ số sức chứa của Xe `V03` biến động như sau:
* **Tải trọng lũy kế mới**:
  $$\text{Tải trọng V03} = 832,70\text{ kg} + 580,60\text{ kg} = \mathbf{1.413,30\text{ kg}}$$
  Mức sử dụng tải trọng mới: $\frac{1.413,30}{2.500} \times 100\% = \mathbf{56,53\%} \le 100\%$ (Thỏa mãn).
* **Thể tích lũy kế mới**:
  $$\text{Thể tích V03} = 3,19\text{ m}^3 + 2,07\text{ m}^3 = \mathbf{5,26\text{ m}^3}$$
  Mức sử dụng thể tích mới: $\frac{5,26}{15} \times 100\% = \mathbf{35,07\%} \le 100\%$ (Thỏa mãn).

### 3. Chi phí cố định Phương án 2
Chỉ điều động $2$ xe (`V01` và `V03`), chi phí cố định là:
$$\text{Chi phí cố định (PA2)} = 2 \text{ xe} \times 800.000\text{ VNĐ/xe} = \mathbf{1.600.000\text{ VNĐ}}$$
$$\text{Mức giảm chi phí cố định} = 2.400.000 - 1.600.000 = \mathbf{800.000\text{ VNĐ}} \quad (\text{Giảm } 33,3\%)$$

---

## IV. BẢNG SO SÁNH CHI TIẾT HAI PHƯƠNG ÁN PHÂN XE

| Tiêu chí So sánh | Phương án 1 (Baseline - 3 Xe) | Phương án 2 (Đề xuất Gom D09 - 2 Xe) | Chênh lệch / Đánh giá |
| :--- | :---: | :---: | :--- |
| **Số xe vận hành** | **3 xe** (`V01`, `V02`, `V03`) | **2 xe** (`V01`, `V03`) | **Giảm 1 xe** (Cắt giảm xe `V02`) |
| **Phân bổ đơn hàng** | • `V01`: D02, D03, D04, D05, D07, D08, D10<br>• `V02`: D09<br>• `V03`: D01, D06 | • `V01`: D02, D03, D04, D05, D07, D08, D10<br>• `V03`: D01, D06, **D09** | Gom thành công `D09` vào xe `V03` |
| **Mức sử dụng tải trọng V01** | $92,94\%$ ($2.323,40\text{ kg}$) | $92,94\%$ ($2.323,40\text{ kg}$) | Không thay đổi |
| **Mức sử dụng tải trọng V02** | $23,22\%$ ($580,60\text{ kg}$) | $0,00\%$ ($0\text{ kg}$) | Xóa bỏ tình trạng chạy thiếu tải |
| **Mức sử dụng tải trọng V03** | $33,31\%$ ($832,70\text{ kg}$) | $56,53\%$ ($1.413,30\text{ kg}$) | Tăng $23,22\%$ (Vẫn nằm trong ngưỡng an toàn) |
| **Mức sử dụng thể tích V03** | $21,27\%$ ($3,19\text{ m}^3$) | $35,07\%$ ($5,26\text{ m}^3$) | Tăng $13,80\%$ (Vẫn nằm trong ngưỡng an toàn) |
| **Tổng Chi phí Cố định** | **$2.400.000\text{ VNĐ}$** | **$1.600.000\text{ VNĐ}$** | **Tiết kiệm $800.000\text{ VNĐ}$** ($33,3\%$) |

---

## V. ĐIỀU CHỈNH CÁCH KẾT LUẬN & ĐÁNH GIÁ KỸ THUẬT

### 1. Hiệu chỉnh thuật ngữ chuyên môn
- **Không sử dụng thuật ngữ *"Hiệu suất tối ưu"* ** khi nhắc đến con số $92,94\%$ lấp đầy của xe `V01`.
- **Định danh chính xác**: Tỷ lệ **"Mức độ sử dụng tải trọng" (Capacity Utilization Rate)**. Chỉ số này phản ánh mức độ điền đầy về mặt khối lượng của thùng xe, chưa thể hiện được hiệu quả tối ưu về mặt chi phí vận hành hay lộ trình di chuyển.

### 2. Định vị bản chất phương pháp phân xe hiện tại
- Phương pháp đang áp dụng hiện tại mới dừng lại ở mức **Phương án Phân xe Cơ sở (Baseline Allocation / Heuristic)**.
- Kết quả này **chưa phải là giải pháp tối ưu toàn cục (Global Optimal Solution)** vì thuật toán mới chỉ xét đến sức chứa (capacity) và vị trí kho cho phép, chưa giải quyết đồng thời các ràng buộc phức tạp trong thực tế như:
  - Khoảng cách di chuyển đường bộ thực tế ($\text{km}$).
  - Khung giờ giao hàng của từng khách hàng (Time Windows - TW).
  - Thời gian chờ và thời gian dỡ hàng tại điểm giao.
  - Tổng chi phí vận tải biến đổi theo quãng đường ($\text{VNĐ/km}$).

### 3. Nhận định về việc chưa kết luận Phương án 2 xe tối ưu hơn
- Mặc dù Phương án 2 giúp giảm ngay **$800.000\text{ VNĐ}$** chi phí cố định do không phải mở xe `V02`, **chưa thể đưa ra kết luận khẳng định Phương án 2 xe tối ưu hơn Phương án 3 xe trên thực tế**.
- **Lý do**:
  - Đơn hàng `D09` nằm ở khu vực Quận 8 (về mặt địa lý gần Kho `K01` tại Phú Nhuận hơn Kho `K02` tại Thủ Đức).
  - Việc chuyển `D09` cho xe `V03` xuất phát từ Kho `K02` (Thủ Đức) đảm nhận có thể làm tăng đáng kể **tổng quãng đường di chuyển thực tế ($\text{km}$)** và **thời gian hoàn thành vòng chạy**.
  - Sự gia tăng về quãng đường có thể làm phát sinh chi phí nhiên liệu/vận hành biến đổi ($\text{VNĐ/km}$) lớn hơn số tiền $800.000\text{ VNĐ}$ tiết kiệm được, hoặc gây nguy cơ vi phạm hạn giao hàng (Time Window) của các đơn hàng khác trên xe `V03`.
- Bài toán đánh đổi giữa Chi phí cố định (Số lượng xe) và Chi phí biến đổi (Quãng đường di chuyển) sẽ tiếp tục được giải quyết triệt để thông qua mô hình tối ưu hóa **Google OR-Tools (MDVRPTW)** ở các tuần tiếp theo.

---

## VI. HƯỚNG DẪN VẬN HÀNH CODE PYTHON VÀ BÀN GIAO FILE KẾT QUẢ

### 1. Cấu trúc các tệp CSV xuất ra
Chương trình Python `script_phan_xe_updated.py` tự động xuất ra 2 tệp kết quả chi tiết tương ứng với 2 phương án:
1. `phan_xe_ban_dau.csv`: Chứa kết quả phân bổ chi tiết của Phương án 1 (Baseline 3 xe).
2. `phan_xe_phuong_an_2xe.csv`: Chứa kết quả phân bổ chi tiết của Phương án 2 (Đề xuất 2 xe).

### 2. Cấu trúc dữ liệu trong file kết quả CSV
Mỗi file CSV bao gồm đầy đủ các trường thông tin chuẩn hóa:
- `ma_don`: Mã đơn hàng (`D01` $\rightarrow$ `D10`).
- `ten_khach_hang`, `dia_chi`: Thông tin điểm giao.
- `kho_phuc_vu_cho_phep`: Chuỗi kho cho phép trích xuất từ `orders.csv`.
- `kho_xuat_phat`: Mã kho thực tế điều động xe (`K01` hoặc `K02`).
- `ma_xe_dam_nhan`: Mã xe được gán (`V01`, `V02`, `V03`).
- `khoi_luong_kg`, `the_tich_m3`: Thông số kích thước đơn hàng.
- `tai_trong_luy_ke_kg`, `the_tich_luy_ke_m3`: Khối lượng và thể tích tích lũy trên xe.
- `muc_su_dung_tai_trong_%`, `muc_su_dung_the_tich_%`: Tỷ lệ lấp đầy xe tương ứng.

### 3. Hướng dẫn chạy nhanh Code Python
1. Đặt file Python `script_phan_xe_updated.py` cùng thư mục với các file dữ liệu `depots.csv`, `vehicles.csv`, `orders (1).csv`.
2. Mở Terminal / PowerShell tại thư mục dự án và thực thi lệnh:
   ```bash
   python script_phan_xe_updated.py
   ```
3. Hệ thống sẽ tự động tính toán, xuất ra 2 file CSV kết quả và in bảng đối sánh chỉ số trực quan ngay trên Terminal.