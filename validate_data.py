#!/usr/bin/env python3
"""
validate_data.py - Kiểm tra dữ liệu CSV của dự án giao hàng (depots / vehicles / orders).

Cách dùng
---------
    python validate_data.py                      # tự tìm: thư mục gốc, data/, data/scenarios/*
    python validate_data.py data/scenarios/S03   # kiểm tra một thư mục cụ thể
    python validate_data.py --report out.csv     # đổi tên file báo cáo (mặc định validation_report.csv)
    python validate_data.py --no-report          # không ghi file báo cáo
    python validate_data.py --strict             # coi WARNING như ERROR khi tính mã thoát

Mã thoát: 0 = không có ERROR | 1 = có ERROR | 2 = không tìm thấy dữ liệu.

Ba mức thông báo
----------------
ERROR   : dữ liệu SAI (trùng mã, thiếu ô, sai toạ độ, sai giờ, tham chiếu kho không tồn tại...).
WARNING : dữ liệu HỢP LỆ nhưng đáng chú ý / có thể không có phương án giao khả thi
          (mã W_FEAS_*: đơn nặng hơn mọi xe, tổng hàng vượt tải đội xe, hạn giao không kịp...).
INFO    : ghi chú (vd: nhiều đơn cùng một địa điểm - được phép, phải có mã đơn riêng).

Chương trình KHÔNG sửa, KHÔNG xoá, KHÔNG bỏ qua dòng lỗi: mỗi lỗi đều ghi rõ
file, dòng, cột và nguyên nhân. Số dòng tính theo file (dòng 1 = tiêu đề, dòng 2 = bản ghi đầu).
"""
import argparse
import csv
import math
import re
import sys
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

# ----------------------------------------------------------------- cấu hình
# Cấu trúc cột GIỮ NGUYÊN theo file gốc / giai_thich_cot.csv. Sửa ở đây nếu nhóm đổi schema.
SCHEMA = {
    "depots": ["ma_kho", "ten_kho", "dia_chi", "vi_do", "kinh_do"],
    "vehicles": ["ma_xe", "ma_kho_quan_ly", "tai_trong_kg", "the_tich_m3",
                 "gio_bat_dau_ca", "gio_ket_thuc_ca", "chi_phi_vnd_km", "chi_phi_co_dinh_vnd"],
    "orders": ["ma_don", "ten_khach_hang", "dia_chi", "vi_do", "kinh_do", "khoi_luong_kg",
               "the_tich_m3", "thoi_gian_phuc_vu_phut", "gio_bat_dau", "gio_ket_thuc",
               "kho_phuc_vu"],
}
ID_PATTERNS = {"ma_kho": r"K\d{2,}", "ma_xe": r"V\d{2,}", "ma_don": r"D\d{2,}"}
# Khung TP.HCM (rộng). Ngoài khung chỉ là WARNING vì có thể nhóm mở rộng khu vực.
HCM_LAT = (10.3, 11.2)
HCM_LON = (106.3, 107.1)
# Ước lượng thô để cảnh báo khả thi về thời gian (KHÔNG phải ma trận đường đi thật).
AVG_SPEED_KMH = 30.0
ROAD_FACTOR = 1.3
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@dataclass
class Issue:
    level: str       # ERROR / WARNING / INFO
    scenario: str
    file: str
    line: object     # số dòng hoặc ""
    column: str
    code: str
    message: str

    def as_row(self):
        return [self.scenario, self.level, self.file, self.line, self.column,
                self.code, self.message]


REPORT_HEADER = ["kich_ban", "muc_do", "file", "dong", "cot", "ma_loi", "noi_dung"]


# ----------------------------------------------------------------- đọc file
class Table:
    def __init__(self, name):
        self.name = name
        self.fname = f"{name}.csv"
        self.rows = []      # list[(line_no, dict)]
        self.ok = False     # đọc được và có đủ cột bắt buộc


def read_table(folder, name, scen, out):
    t = Table(name)
    path = Path(folder) / t.fname
    if not path.is_file():
        out.append(Issue("ERROR", scen, t.fname, "", "", "E_FILE_MISSING",
                         f"Không tìm thấy file {t.fname} trong {folder}"))
        return t
    raw = path.read_bytes()
    if not raw.strip():
        out.append(Issue("ERROR", scen, t.fname, 1, "", "E_FILE_EMPTY", "File rỗng"))
        return t
    if not raw.startswith(b"\xef\xbb\xbf"):
        out.append(Issue("WARNING", scen, t.fname, 1, "", "W_NO_BOM",
                         "File không có BOM UTF-8; quy ước dự án là UTF-8 có BOM "
                         "(đọc bằng pandas: encoding='utf-8-sig')"))
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        out.append(Issue("ERROR", scen, t.fname, "", "", "E_ENCODING",
                         f"Không giải mã được UTF-8: {e}"))
        return t
    reader = csv.reader(text.splitlines(keepends=True))
    try:
        header = [h.strip() for h in next(reader)]
    except StopIteration:
        out.append(Issue("ERROR", scen, t.fname, 1, "", "E_FILE_EMPTY", "File không có tiêu đề"))
        return t
    expected = SCHEMA[name]
    missing = [c for c in expected if c not in header]
    extra = [c for c in header if c not in expected]
    for c in missing:
        out.append(Issue("ERROR", scen, t.fname, 1, c, "E_COLUMN_MISSING",
                         f"Thiếu cột bắt buộc '{c}'"))
    for c in extra:
        out.append(Issue("WARNING", scen, t.fname, 1, c, "W_COLUMN_EXTRA",
                         f"Cột '{c}' không có trong schema chuẩn (giai_thich_cot.csv)"))
    dup_cols = {c for c in header if header.count(c) > 1}
    for c in sorted(dup_cols):
        out.append(Issue("ERROR", scen, t.fname, 1, c, "E_COLUMN_DUP", f"Cột '{c}' xuất hiện nhiều lần"))
    if not missing and not extra and header != expected:
        out.append(Issue("WARNING", scen, t.fname, 1, "", "W_COLUMN_ORDER",
                         "Thứ tự cột khác schema chuẩn (đọc theo tên cột vẫn được, "
                         "nhưng code đọc theo vị trí sẽ sai)"))
    if missing or dup_cols:
        return t
    t.ok = True
    for rec in reader:
        line = reader.line_num
        if not rec or all(not c.strip() for c in rec):
            out.append(Issue("WARNING", scen, t.fname, line, "", "W_BLANK_LINE", "Dòng trống"))
            continue
        if len(rec) != len(header):
            out.append(Issue("ERROR", scen, t.fname, line, "", "E_FIELD_COUNT",
                             f"Dòng có {len(rec)} ô nhưng tiêu đề có {len(header)} cột "
                             "(kiểm tra dấu phẩy trong địa chỉ - cần đặt trong dấu nháy kép)"))
            continue
        t.rows.append((line, dict(zip(header, rec))))
    if not t.rows:
        out.append(Issue("ERROR", scen, t.fname, "", "", "E_NO_DATA", "File không có dòng dữ liệu nào"))
    return t


# ----------------------------------------------------------------- tiện ích kiểm tra
def get_text(row, col, line, t, scen, out, code_prefix="E"):
    v = row[col]
    if not v.strip():
        out.append(Issue("ERROR", scen, t.fname, line, col, "E_EMPTY", f"Thiếu giá trị ở cột '{col}'"))
        return None
    if v != v.strip():
        out.append(Issue("WARNING", scen, t.fname, line, col, "W_WHITESPACE",
                         f"Giá trị '{v}' có khoảng trắng thừa ở đầu/cuối"))
    return v.strip()


def get_float(row, col, line, t, scen, out):
    v = row[col].strip()
    if not v:
        out.append(Issue("ERROR", scen, t.fname, line, col, "E_EMPTY", f"Thiếu giá trị ở cột '{col}'"))
        return None
    try:
        x = float(v)
    except ValueError:
        hint = " (dùng dấu chấm làm dấu thập phân, không dùng dấu phẩy)" if "," in v else ""
        out.append(Issue("ERROR", scen, t.fname, line, col, "E_NOT_NUMBER",
                         f"'{v}' không phải số{hint}"))
        return None
    if math.isnan(x) or math.isinf(x):
        out.append(Issue("ERROR", scen, t.fname, line, col, "E_NOT_NUMBER", f"'{v}' không phải số hữu hạn"))
        return None
    return x


def get_time(row, col, line, t, scen, out):
    v = row[col].strip()
    if not v:
        out.append(Issue("ERROR", scen, t.fname, line, col, "E_EMPTY", f"Thiếu giá trị ở cột '{col}'"))
        return None
    if not TIME_RE.match(v):
        out.append(Issue("ERROR", scen, t.fname, line, col, "E_TIME_FORMAT",
                         f"'{v}' sai định dạng giờ, phải là HH:MM (00:00-23:59)"))
        return None
    h, m = v.split(":")
    return int(h) * 60 + int(m)


def check_id(row, col, line, t, scen, out, seen):
    v = get_text(row, col, line, t, scen, out)
    if v is None:
        return None
    if not re.fullmatch(ID_PATTERNS[col], v):
        out.append(Issue("WARNING", scen, t.fname, line, col, "W_ID_FORMAT",
                         f"Mã '{v}' không theo quy ước {ID_PATTERNS[col]} (vd K01, V01, D01)"))
    if v in seen:
        out.append(Issue("ERROR", scen, t.fname, line, col, "E_DUP_ID",
                         f"Mã '{v}' bị trùng với dòng {seen[v]}"))
    else:
        seen[v] = line
    return v


def check_coords(row, line, t, scen, out, ident):
    lat = get_float(row, "vi_do", line, t, scen, out)
    lon = get_float(row, "kinh_do", line, t, scen, out)
    if lat is None or lon is None:
        return None
    bad = False
    if not -90 <= lat <= 90:
        hint = " (có thể đã đảo nhầm vĩ độ và kinh độ)" if -90 <= lon <= 90 else ""
        out.append(Issue("ERROR", scen, t.fname, line, "vi_do", "E_COORD_RANGE",
                         f"{ident}: vĩ độ {lat} ngoài khoảng [-90, 90]{hint}"))
        bad = True
    if not -180 <= lon <= 180:
        out.append(Issue("ERROR", scen, t.fname, line, "kinh_do", "E_COORD_RANGE",
                         f"{ident}: kinh độ {lon} ngoài khoảng [-180, 180]"))
        bad = True
    if bad:
        return None
    if lat == 0 and lon == 0:
        out.append(Issue("ERROR", scen, t.fname, line, "vi_do", "E_COORD_ZERO",
                         f"{ident}: toạ độ (0, 0) là giá trị mặc định, không phải vị trí thật"))
        return None
    if not (HCM_LAT[0] <= lat <= HCM_LAT[1] and HCM_LON[0] <= lon <= HCM_LON[1]):
        out.append(Issue("WARNING", scen, t.fname, line, "vi_do", "W_COORD_OUTSIDE_HCM",
                         f"{ident}: toạ độ ({lat}, {lon}) nằm ngoài khu vực TP.HCM, "
                         "kiểm tra lại với TV4"))
    return lat, lon


def haversine_km(a, b):
    r = 6371.0088
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


# ----------------------------------------------------------------- kiểm tra từng file
def check_depots(t, scen, out):
    depots, seen, coords = {}, {}, {}
    for line, row in t.rows:
        ma = check_id(row, "ma_kho", line, t, scen, out, seen)
        get_text(row, "ten_kho", line, t, scen, out)
        get_text(row, "dia_chi", line, t, scen, out)
        c = check_coords(row, line, t, scen, out, ma or "kho")
        if ma and c:
            depots[ma] = c
            if c in coords:
                out.append(Issue("WARNING", scen, t.fname, line, "vi_do", "W_DEPOT_SAME_COORD",
                                 f"Kho {ma} trùng toạ độ với kho {coords[c]}"))
            coords.setdefault(c, ma)
        elif ma:
            depots[ma] = None
    return depots


def check_vehicles(t, depots, scen, out):
    vehs, seen = [], {}
    for line, row in t.rows:
        ma = check_id(row, "ma_xe", line, t, scen, out, seen)
        kho = get_text(row, "ma_kho_quan_ly", line, t, scen, out)
        if kho and kho not in depots:
            out.append(Issue("ERROR", scen, t.fname, line, "ma_kho_quan_ly", "E_REF_DEPOT",
                             f"Xe {ma}: kho '{kho}' không tồn tại trong depots.csv "
                             f"(kho hợp lệ: {', '.join(sorted(depots)) or 'không có'})"))
        kg = get_float(row, "tai_trong_kg", line, t, scen, out)
        m3 = get_float(row, "the_tich_m3", line, t, scen, out)
        for col, v in (("tai_trong_kg", kg), ("the_tich_m3", m3)):
            if v is not None and v <= 0:
                out.append(Issue("ERROR", scen, t.fname, line, col, "E_NON_POSITIVE",
                                 f"Xe {ma}: {col} = {v} phải > 0"))
        s = get_time(row, "gio_bat_dau_ca", line, t, scen, out)
        e = get_time(row, "gio_ket_thuc_ca", line, t, scen, out)
        if s is not None and e is not None and s >= e:
            out.append(Issue("ERROR", scen, t.fname, line, "gio_ket_thuc_ca", "E_TIME_ORDER",
                             f"Xe {ma}: giờ kết thúc ca {row['gio_ket_thuc_ca']} phải sau giờ bắt đầu "
                             f"{row['gio_bat_dau_ca']}"))
        km = get_float(row, "chi_phi_vnd_km", line, t, scen, out)
        fx = get_float(row, "chi_phi_co_dinh_vnd", line, t, scen, out)
        for col, v in (("chi_phi_vnd_km", km), ("chi_phi_co_dinh_vnd", fx)):
            if v is not None and v < 0:
                out.append(Issue("ERROR", scen, t.fname, line, col, "E_NEGATIVE",
                                 f"Xe {ma}: {col} = {v} không được âm"))
        if None not in (ma, kho, kg, m3, s, e) and kg > 0 and m3 > 0 and s < e:
            vehs.append(dict(ma=ma, kho=kho, kg=kg, m3=m3, s=s, e=e))
    return vehs


def check_orders(t, depots, scen, out):
    orders, seen, locs = [], {}, {}
    for line, row in t.rows:
        ma = check_id(row, "ma_don", line, t, scen, out, seen)
        ident = ma or f"dòng {line}"
        get_text(row, "ten_khach_hang", line, t, scen, out)
        get_text(row, "dia_chi", line, t, scen, out)
        c = check_coords(row, line, t, scen, out, ident)
        kg = get_float(row, "khoi_luong_kg", line, t, scen, out)
        m3 = get_float(row, "the_tich_m3", line, t, scen, out)
        for col, v in (("khoi_luong_kg", kg), ("the_tich_m3", m3)):
            if v is not None and v <= 0:
                out.append(Issue("ERROR", scen, t.fname, line, col, "E_NON_POSITIVE",
                                 f"Đơn {ident}: {col} = {v} phải > 0"))
        sv = get_float(row, "thoi_gian_phuc_vu_phut", line, t, scen, out)
        if sv is not None:
            if sv <= 0:
                out.append(Issue("ERROR", scen, t.fname, line, "thoi_gian_phuc_vu_phut", "E_NON_POSITIVE",
                                 f"Đơn {ident}: thời gian phục vụ {sv} phút phải > 0"))
            elif sv != int(sv):
                out.append(Issue("ERROR", scen, t.fname, line, "thoi_gian_phuc_vu_phut", "E_NOT_INTEGER",
                                 f"Đơn {ident}: thời gian phục vụ {sv} phải là số phút nguyên"))
        s = get_time(row, "gio_bat_dau", line, t, scen, out)
        e = get_time(row, "gio_ket_thuc", line, t, scen, out)
        if s is not None and e is not None and s >= e:
            out.append(Issue("ERROR", scen, t.fname, line, "gio_ket_thuc", "E_TIME_ORDER",
                             f"Đơn {ident}: hạn chót {row['gio_ket_thuc']} phải sau giờ bắt đầu "
                             f"{row['gio_bat_dau']}"))
            s = e = None
        # kho phục vụ
        raw = row["kho_phuc_vu"].strip()
        allowed = []
        if not raw:
            out.append(Issue("ERROR", scen, t.fname, line, "kho_phuc_vu", "E_EMPTY",
                             f"Đơn {ident}: thiếu kho phục vụ"))
        else:
            parts = [p.strip() for p in raw.split(";")]
            for p in parts:
                if not p:
                    out.append(Issue("ERROR", scen, t.fname, line, "kho_phuc_vu", "E_REF_DEPOT",
                                     f"Đơn {ident}: kho_phuc_vu '{raw}' có phần tử rỗng "
                                     "(các kho cách nhau bằng dấu ';')"))
                elif p not in depots:
                    out.append(Issue("ERROR", scen, t.fname, line, "kho_phuc_vu", "E_REF_DEPOT",
                                     f"Đơn {ident}: kho '{p}' không tồn tại trong depots.csv "
                                     f"(kho hợp lệ: {', '.join(sorted(depots)) or 'không có'})"))
                elif p in allowed:
                    out.append(Issue("WARNING", scen, t.fname, line, "kho_phuc_vu", "W_DEPOT_REPEAT",
                                     f"Đơn {ident}: kho '{p}' lặp lại trong kho_phuc_vu"))
                else:
                    allowed.append(p)
        if c:
            if c in locs:
                out.append(Issue("INFO", scen, t.fname, line, "vi_do", "I_SAME_LOCATION",
                                 f"Đơn {ident} cùng địa điểm với đơn {locs[c]} "
                                 "(được phép, mỗi đơn có mã riêng)"))
            else:
                locs[c] = ident
        # cảnh báo: khung giờ hợp lệ nhưng quá ngắn để dỡ hàng
        if None not in (s, e, sv) and sv > 0 and s + sv > e:
            out.append(Issue("WARNING", scen, t.fname, line, "gio_ket_thuc", "W_WINDOW_TOO_SHORT",
                             f"Đơn {ident}: khung {row['gio_bat_dau']}-{row['gio_ket_thuc']} "
                             f"({e - s} phút) ngắn hơn thời gian dỡ hàng {int(sv)} phút -> không thể giao đúng hạn"))
        if None not in (ma, kg, m3, sv, s, e, c) and kg > 0 and m3 > 0 and sv > 0 and allowed:
            orders.append(dict(ma=ma, line=line, kg=kg, m3=m3, sv=sv, s=s, e=e,
                               allowed=allowed, loc=c))
    return orders


# ----------------------------------------------------------------- cảnh báo khả thi
def check_feasibility(depots, vehs, orders, scen, out):
    """Dữ liệu HỢP LỆ nhưng có thể không có phương án giao đủ hàng -> chỉ WARNING."""
    if not vehs or not orders:
        return
    ot = "orders.csv"
    by_depot = {}
    for v in vehs:
        by_depot.setdefault(v["kho"], []).append(v)

    for o in orders:
        cands = [v for d in o["allowed"] for v in by_depot.get(d, [])]
        if not cands:
            out.append(Issue("WARNING", scen, ot, o["line"], "kho_phuc_vu", "W_FEAS_NO_VEHICLE",
                             f"Đơn {o['ma']}: các kho phục vụ {';'.join(o['allowed'])} không có xe nào"))
            continue
        max_kg, max_m3 = max(v["kg"] for v in cands), max(v["m3"] for v in cands)
        if o["kg"] > max_kg:
            out.append(Issue("WARNING", scen, ot, o["line"], "khoi_luong_kg", "W_FEAS_ORDER_TOO_HEAVY",
                             f"Đơn {o['ma']} nặng {o['kg']} kg > tải trọng lớn nhất của xe có thể phục vụ "
                             f"({max_kg:g} kg) -> không xe nào chở được"))
        if o["m3"] > max_m3:
            out.append(Issue("WARNING", scen, ot, o["line"], "the_tich_m3", "W_FEAS_ORDER_TOO_BULKY",
                             f"Đơn {o['ma']} chiếm {o['m3']} m3 > thể tích lớn nhất của xe có thể phục vụ "
                             f"({max_m3:g} m3) -> không xe nào chở được"))
        # ước lượng thời gian tốt nhất: xe xuất phát từ kho đầu ca, chạy thẳng tới điểm giao
        best_ok = False
        for v in cands:
            dep = depots.get(v["kho"])
            if dep is None:
                best_ok = True
                break
            travel = haversine_km(dep, o["loc"]) * ROAD_FACTOR / AVG_SPEED_KMH * 60
            arrive = max(v["s"] + travel, o["s"])
            finish = arrive + o["sv"]
            if finish <= o["e"] and finish <= v["e"]:
                best_ok = True
                break
        if not best_ok:
            out.append(Issue("WARNING", scen, ot, o["line"], "gio_ket_thuc", "W_FEAS_TIME",
                             f"Đơn {o['ma']}: ngay cả khi xe đi thẳng từ kho đầu ca (ước lượng "
                             f"{AVG_SPEED_KMH:g} km/h, hệ số đường {ROAD_FACTOR}) vẫn không kịp hạn "
                             f"{hm(o['e'])} hoặc hết ca"))

    # tổng tải: với mọi tập kho S, đơn chỉ phục vụ được bởi kho thuộc S phải nằm gọn trong xe của S
    ids = sorted(depots)
    if len(ids) <= 12:
        for r in range(1, len(ids) + 1):
            for sub in combinations(ids, r):
                ss = set(sub)
                grp = [o for o in orders if set(o["allowed"]) <= ss]
                if not grp:
                    continue
                cap_kg = sum(v["kg"] for v in vehs if v["kho"] in ss)
                cap_m3 = sum(v["m3"] for v in vehs if v["kho"] in ss)
                w, vol = sum(o["kg"] for o in grp), sum(o["m3"] for o in grp)
                scope = "toàn bộ đội xe" if len(ss) == len(ids) else f"xe của kho {', '.join(sub)}"
                if w > cap_kg:
                    out.append(Issue("WARNING", scen, ot, "", "khoi_luong_kg", "W_FEAS_FLEET_WEIGHT",
                                     f"{len(grp)} đơn chỉ phục vụ được bởi {scope} có tổng {w:.1f} kg "
                                     f"> tổng tải trọng {cap_kg:g} kg (một chuyến/xe) -> không thể giao hết "
                                     "nếu mỗi xe chỉ chạy một chuyến"))
                if vol > cap_m3:
                    out.append(Issue("WARNING", scen, ot, "", "the_tich_m3", "W_FEAS_FLEET_VOLUME",
                                     f"{len(grp)} đơn chỉ phục vụ được bởi {scope} có tổng {vol:.2f} m3 "
                                     f"> tổng thể tích {cap_m3:g} m3 (một chuyến/xe) -> không thể giao hết "
                                     "nếu mỗi xe chỉ chạy một chuyến"))


def hm(m):
    m = int(m)
    return f"{m // 60:02d}:{m % 60:02d}"


# ----------------------------------------------------------------- đối chiếu giai_thich_cot
def find_doc(folder):
    p = Path(folder).resolve()
    for cand in [p, *p.parents][:4]:
        f = cand / "giai_thich_cot.csv"
        if f.is_file():
            return f
    return None


def check_doc(folder, scen, out):
    f = find_doc(folder)
    if f is None:
        return
    try:
        with open(f, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))[1:]
    except (OSError, UnicodeDecodeError):
        return
    documented = {k: [] for k in SCHEMA}
    for r in rows:
        if len(r) >= 2 and r[0] in documented:
            documented[r[0]].append(r[1])
    for sheet, cols in SCHEMA.items():
        if not documented[sheet]:
            continue
        for c in cols:
            if c not in documented[sheet]:
                out.append(Issue("WARNING", scen, "giai_thich_cot.csv", "", c, "W_DOC_MISSING",
                                 f"Cột {sheet}.{c} chưa được giải thích trong {f.name}"))
        for c in documented[sheet]:
            if c not in cols:
                out.append(Issue("WARNING", scen, "giai_thich_cot.csv", "", c, "W_DOC_STALE",
                                 f"{f.name} mô tả cột {sheet}.{c} nhưng validator không có cột này "
                                 "(kiểm tra SCHEMA trong validate_data.py)"))


# ----------------------------------------------------------------- điều phối
def validate_folder(folder, scen):
    out = []
    tabs = {n: read_table(folder, n, scen, out) for n in SCHEMA}
    depots = check_depots(tabs["depots"], scen, out) if tabs["depots"].ok else {}
    vehs = check_vehicles(tabs["vehicles"], depots, scen, out) if tabs["vehicles"].ok else []
    orders = check_orders(tabs["orders"], depots, scen, out) if tabs["orders"].ok else []
    check_feasibility(depots, vehs, orders, scen, out)
    check_doc(folder, scen, out)
    return out


def discover(root):
    root = Path(root)
    cands = [root, root / "data"]
    sc = root / "data" / "scenarios"
    if sc.is_dir():
        cands += sorted(p for p in sc.iterdir() if p.is_dir())
    return [c for c in cands if (c / "depots.csv").is_file()]


def scen_name(folder, root):
    try:
        rel = Path(folder).resolve().relative_to(Path(root).resolve())
        return "du_lieu_goc" if str(rel) == "." else rel.as_posix().replace("data/scenarios/", "")
    except ValueError:
        return Path(folder).name


def main(argv=None):
    ap = argparse.ArgumentParser(description="Kiểm tra dữ liệu CSV (depots/vehicles/orders).")
    ap.add_argument("paths", nargs="*", help="thư mục cần kiểm tra (mặc định: tự tìm)")
    ap.add_argument("--report", default="validation_report.csv", help="file báo cáo CSV")
    ap.add_argument("--no-report", action="store_true", help="không ghi file báo cáo")
    ap.add_argument("--strict", action="store_true", help="WARNING cũng làm mã thoát = 1")
    ap.add_argument("--quiet", action="store_true", help="chỉ in ERROR và tổng kết")
    args = ap.parse_args(argv)

    root = Path.cwd()
    folders = [Path(p) for p in args.paths] if args.paths else discover(root)
    if not folders:
        print("Không tìm thấy thư mục dữ liệu (cần depots.csv). Chỉ rõ đường dẫn, "
              "vd: python validate_data.py data/scenarios/S01", file=sys.stderr)
        return 2

    all_issues, summary = [], []
    for f in folders:
        scen = scen_name(f, root)
        issues = validate_folder(f, scen)
        all_issues += issues
        n = {lv: sum(1 for i in issues if i.level == lv) for lv in ("ERROR", "WARNING", "INFO")}
        summary.append((scen, n))
        print(f"\n=== {scen}  ({f}) ===")
        shown = [i for i in issues if not (args.quiet and i.level != "ERROR")]
        for i in shown:
            where = i.file + (f" dòng {i.line}" if i.line != "" else "")
            col = f" cột {i.column}" if i.column else ""
            print(f"[{i.level}] {where}{col} ({i.code}): {i.message}")
        if not issues:
            print("OK - không phát hiện vấn đề")

    print("\n--- TỔNG KẾT ---")
    for scen, n in summary:
        status = "LỖI DỮ LIỆU" if n["ERROR"] else "dữ liệu hợp lệ"
        print(f"{scen:12s} ERROR={n['ERROR']:<3d} WARNING={n['WARNING']:<3d} INFO={n['INFO']:<3d} -> {status}")

    if not args.no_report:
        with open(args.report, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(REPORT_HEADER)
            if all_issues:
                w.writerows(i.as_row() for i in all_issues)
            else:
                w.writerow(["(tất cả)", "OK", "", "", "", "", "Không phát hiện lỗi hay cảnh báo"])
        print(f"Đã ghi báo cáo: {args.report}")

    errors = sum(1 for i in all_issues if i.level == "ERROR")
    warns = sum(1 for i in all_issues if i.level == "WARNING")
    return 1 if errors or (args.strict and warns) else 0


if __name__ == "__main__":
    sys.exit(main())
