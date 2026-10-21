# BÁO CÁO GIẢI TRÌNH LOGIC PHÂN XE BAN ĐẦU (TUẦN 1 - 2)

* **Dự án**: Xây dựng ứng dụng Windows tối ưu phân xe và định tuyến giao hàng B2B từ nhiều kho (Multi-Depot)
* **Thành viên thực hiện**: Thành viên 2 (Phụ trách Thuật toán)
* **Nhiệm vụ**: Xây dựng quy tắc phân xe ban đầu, kiểm tra sức chứa và xuất báo cáo đối soát

---

## I. Tổng quan Dữ liệu Đầu vào

Dữ liệu được tiếp nhận từ Thành viên 1 bao gồm 3 tệp cơ bản:
1. **Danh sách Kho (`depots.csv`)**: 2 kho chính bao gồm Kho K01 (Phú Nhuận) và Kho K02 (Thủ Đức).
2. **Đội xe (`vehicles.csv`)**: 4 xe vận tải.
   * Xe `V01`, `V02`: Thuộc quản lý của Kho K01.
   * Xe `V03`, `V04`: Thuộc quản lý của Kho K02.
   * Ràng buộc sức chứa mỗi xe: Tải trọng tối đa $2.500\text{ kg}$, thể tích thùng xe tối đa $15\text{ m}^3$.
3. **Danh sách Đơn hàng (`orders.csv`)**: 10 đơn hàng B2B ($D01 \rightarrow D10$).
   * Tổng khối lượng nhu cầu: $3.736,70\text{ kg}$.
   * Tổng thể tích nhu cầu: $13,01\text{ m}^3$.

---

## II. Quy tắc Phân xe Ban đầu (Heuristic Logic)

Để đảm bảo xe không vi phạm tải trọng và gán đúng kho phục vụ, thuật toán xử lý theo 3 bước:

### 1. Phân kho ưu tiên dựa trên khoảng cách địa lý (Nearest Depot)
Sử dụng công thức **Haversine** để tính khoảng cách đường chim bay từ tọa độ đơn hàng $(\text{lat}_i, \text{lon}_i)$ đến từng kho $(\text{lat}_k, \text{lon}_k)$:

$$d = 2 R \cdot \arcsin\left(\sqrt{\sin^2\left(\frac{\Delta \text{lat}}{2}\right) + \cos(\text{lat}_1)\cos(\text{lat}_2)\sin^2\left(\frac{\Delta \text{lon}}{2}\right)}\right)$$

Đơn hàng sẽ ưu tiên gán cho kho có khoảng cách $d$ ngắn nhất.

### 2. Kiểm tra Ràng buộc Sức chứa (Capacity Check)
Một đơn hàng chỉ được xếp vào xe nếu thỏa mãn đồng thời 2 điều kiện:

$$\sum \text{Khối lượng đơn} \le 2.500\text{ kg}$$

$$\sum \text{Thể tích đơn} \le 15\text{ m}^3$$

### 3. Quy tắc gán xe (First-Fit Allocation)
* Lặp qua từng đơn hàng trong danh sách.
* Lọc danh sách xe thuộc kho ưu tiên.
* Chọn xe đầu tiên còn đủ sức chứa cả về khối lượng và thể tích để gán đơn.
* Nếu các xe ở kho ưu tiên đã đầy, chuyển sang xét các xe thuộc kho còn lại.

---

## III. Kết quả Phân xe & Hiệu suất Đội xe

### 1. Bảng phân bổ đơn hàng chi tiết (`phan_xe_ban_dau.csv`)

| Mã đơn | Tên khách hàng | Kho xuất phát | Mã xe | Khối lượng ($\text{kg}$) | Thể tích ($\text{m}^3$) | Tải trọng lũy kế ($\text{kg}$) | % Lấp đầy tải trọng | % Lấp đầy thể tích |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **D01** | Metro An Phú | K02 | **V03** | $545,30$ | $2,11$ | $545,30$ | $21,81\%$ | $14,07\%$ |
| **D02** | Chợ Bến Thành | K01 | **V01** | $309,40$ | $0,62$ | $309,40$ | $12,38\%$ | $4,13\%$ |
| **D03** | Landmark 81 | K01 | **V01** | $286,60$ | $0,87$ | $596,00$ | $23,84\%$ | $9,93\%$ |
| **D04** | Aeon Tân Phú | K01 | **V01** | $411,60$ | $1,72$ | $1.007,60$ | $40,30\%$ | $21,40\%$ |
| **D05** | Crescent Mall | K01 | **V01** | $317,90$ | $1,47$ | $1.325,50$ | $53,02\%$ | $31,20\%$ |
| **D06** | Gigamall | K02 | **V03** | $287,40$ | $1,08$ | $832,70$ | $33,31\%$ | $21,27\%$ |
| **D07** | GO! Gò Vấp | K01 | **V01** | $343,30$ | $1,46$ | $1.668,80$ | $66,75\%$ | $40,93\%$ |
| **D08** | BV Chợ Rẫy | K01 | **V01** | $349,40$ | $0,73$ | $2.018,20$ | $80,73\%$ | $45,80\%$ |
| **D09** | Chợ Phú Định | K01 | **V02** | $580,60$ | $2,07$ | $580,60$ | $23,22\%$ | $13,80\%$ |
| **D10** | Sân bay TSN | K01 | **V01** | $305,20$ | $0,88$ | $2.323,40$ | **$92,94\%$** | **$51,67\%$** |

### 2. Thống kê tỷ lệ lấp đầy đội xe
* **Xe V01 (Kho K01)**: Phục vụ **7 đơn hàng**. Tải trọng đạt **$92,94\%$** ($2.323,40 / 2.500\text{ kg}$), Thể tích đạt **$51,67\%$** ($7,75 / 15\text{ m}^3$).
* **Xe V02 (Kho K01)**: Phục vụ **1 đơn hàng**. Tải trọng đạt **$23,22\%$** ($580,60 / 2.500\text{ kg}$).
* **Xe V03 (Kho K02)**: Phục vụ **2 đơn hàng**. Tải trọng đạt **$33,31\%$** ($832,70 / 2.500\text{ kg}$).
* **Xe V04 (Kho K02)**: Chưa cần sử dụng (Đóng vai trò dự phòng).

---

## IV. Đánh giá & Hạn chế (Tiền đề nâng cấp lên Google OR-Tools)

### 1. Điểm đạt được
* **Tuân thủ tuyệt đối quy tắc an toàn**: $100\%$ xe không bị quá tải trọng hoặc vượt thể tích.
* **Gán đúng kho quản lý**: Đơn hàng khu vực TP. Thủ Đức được gán hợp lý cho Kho K02.
* **Xe V01 đạt hiệu suất tối ưu cao**: Tận dụng đến $92,94\%$ năng lực chở hàng.

### 2. Những hạn chế chưa giải quyết được
* **Chưa sắp xếp thứ tự giao (Routing)**: Thuật toán mới chỉ gom đơn vào xe, chưa đưa ra lộ trình đi theo thứ tự ghé điểm sao cho tổng quãng đường là ngắn nhất.
* **Chưa kiểm soát Khung giờ giao (Time Windows)**: Các trường `gio_bat_dau` và `gio_ket_thuc` hiện chỉ lưu trữ dữ liệu, chưa được tính toán cùng thời gian di chuyển thực tế.
* **Chưa tính hàm chi phí tối ưu toàn cục**: Chưa tính toán chi phí cố định mở xe ($800.000\text{ VNĐ}$) và chi phí di chuyển ($12.000\text{ VNĐ/km}$).

### 3. Kế hoạch tuần tiếp theo
Ở các tuần tiếp theo, nhóm sẽ ứng dụng bộ giải **Google OR-Tools Routing Solver** để giải bài toán **$MDVRPTW$** (Multi-Depot Vehicle Routing Problem with Time Windows), giúp tối ưu đồng thời cả 3 yếu tố: **Phân xe + Tối ưu lộ trình + Đảm bảo khung giờ giao hàng**.