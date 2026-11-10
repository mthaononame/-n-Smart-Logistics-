#!/usr/bin/env python3
"""
generate_scenarios.py - Sinh bộ dữ liệu mở rộng và 5 kịch bản kiểm thử S01-S05.

CÁCH DÙNG
---------
    python generate_scenarios.py                 # sinh S01-S05 + scenario_description.csv, rồi tự kiểm tra
    python generate_scenarios.py --check         # chỉ so sánh với file đang có trên đĩa (dùng trước khi commit)
    python generate_scenarios.py --list          # liệt kê kịch bản
    python generate_scenarios.py --only S03,S05  # chỉ ghi lại một số kịch bản
    python generate_scenarios.py --seed 7        # đổi seed (mặc định 20261110 - KHÔNG đổi khi bàn giao)
    python generate_scenarios.py --no-validate   # bỏ bước tự kiểm tra bằng validate_data.py

Mã thoát: 0 = thành công | 1 = kiểm tra thất bại (kịch bản sai thiết kế, có ERROR, hoặc --check lệch)
          | 2 = dữ liệu gốc / tham số có vấn đề.

ĐẶC ĐIỂM
--------
* Đọc dữ liệu GỐC (depots.csv, vehicles.csv, orders.csv ở thư mục gốc dự án): 2 kho, mẫu xe và
  10 đơn D01-D10 lấy từ file của nhóm, nên khi nhóm sửa dữ liệu gốc, chạy lại là các kịch bản đồng bộ theo.
  Thiếu file gốc thì dùng bộ dữ liệu nhúng sẵn trong script.
* KHÔNG BAO GIỜ ghi đè depots/vehicles/orders.csv gốc: chỉ ghi vào data/scenarios/.
* Cột và thứ tự cột lấy từ SCHEMA của validate_data.py (một nguồn duy nhất). Nếu file gốc có cột khác
  schema thì dừng và báo rõ, không tự đổi tên cột.
* Seed cố định => chạy lại luôn cho cùng kết quả byte-by-byte (xác nhận bằng --check).
* Sau khi sinh, tự kiểm tra: (1) mỗi kịch bản còn đúng mục đích thiết kế (vd S05 vẫn thiếu năng lực,
  S04 đúng 8/8/8 đơn theo kho), (2) validate_data.py không báo ERROR, (3) chỉ S05 có cảnh báo W_FEAS_*.

PHÂN BIỆT DỮ LIỆU
-----------------
* THỰC (công khai): tên/địa chỉ/toạ độ kho và điểm giao. Toạ độ D11-D28 là XẤP XỈ, cần TV4 xác minh.
* MÔ PHỎNG: khối lượng, thể tích, thời gian dỡ, hạn giao, đội xe, chi phí, kho_phuc_vu.
"""
import argparse
import csv
import io
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:                                    # nguồn schema duy nhất = validate_data.py
    import validate_data as VD
    SCHEMA = VD.SCHEMA
except ImportError:                     # vẫn chạy được nếu thiếu validator (bỏ qua bước tự kiểm tra)
    VD = None
    SCHEMA = {
        "depots": ["ma_kho", "ten_kho", "dia_chi", "vi_do", "kinh_do"],
        "vehicles": ["ma_xe", "ma_kho_quan_ly", "tai_trong_kg", "the_tich_m3", "gio_bat_dau_ca",
                     "gio_ket_thuc_ca", "chi_phi_vnd_km", "chi_phi_co_dinh_vnd"],
        "orders": ["ma_don", "ten_khach_hang", "dia_chi", "vi_do", "kinh_do", "khoi_luong_kg",
                   "the_tich_m3", "thoi_gian_phuc_vu_phut", "gio_bat_dau", "gio_ket_thuc",
                   "kho_phuc_vu"],
    }

DEFAULT_SEED = 20261110
DEFAULT_OUT = HERE / "data" / "scenarios"
BULKY_M3_PER_TON = 20.0     # m3 trên mỗi tấn: từ ngưỡng này trở lên coi là "nhẹ nhưng cồng kềnh"

# ======================================================================================
# CẤU HÌNH KỊCH BẢN - chỉnh số liệu ở đây rồi chạy lại script (đừng sửa tay file CSV)
# ======================================================================================
CONFIG = {
    "S01": dict(n_orders=25, vehicles_per_depot=2),
    "S02": dict(n_orders=28, vehicles_per_depot=3, target_kg=13200.0),
    "S03": dict(n_orders=25, vehicles_per_depot=3,
                start_choices=[510, 540, 570, 600],          # 08:30 - 10:00
                slack_choices=[40, 45, 50, 60, 70, 75]),     # phút dư ngoài thời gian dỡ
    "S04": dict(n_orders=24, vehicles_per_depot=2,
                only_k01=["D04", "D07", "D08", "D09", "D12", "D13", "D14", "D20"],
                only_k02=["D01", "D06", "D15", "D18", "D19", "D22", "D23", "D24"]),
    "S05": dict(n_orders=26, vehicles_per_depot=2, target_kg=11200.0,
                oversized=("D26", 2900.0, 9.8),              # (mã đơn, kg, m3): nặng hơn mọi xe
                bulky=[("D05", 140.0, 8.6), ("D10", 110.0, 9.2), ("D17", 95.0, 8.9)]),
}

# --------------------------------------------------------------------------------------
# Bộ dữ liệu nhúng sẵn (dùng khi không có file gốc). Trùng với 3 file gốc hiện tại.
# --------------------------------------------------------------------------------------
DEFAULT_DEPOTS = [
    ["K01", "SPX Express - Bưu cục PN/Cầu Kiệu", "53 Cù Lao, Cầu Kiệu, Hồ Chí Minh 72222, Việt Nam",
     "10.80013297922369", "106.6893717551218"],
    ["K02", "Kho J&T 028H87", "RQF5+C29, Thủ Đức, Hồ Chí Minh, Việt Nam",
     "10.82450621022111", "106.7561346402375"],
]
DEFAULT_VEHICLE = {"tai_trong_kg": "2500", "the_tich_m3": "15", "gio_bat_dau_ca": "06:00",
                   "gio_ket_thuc_ca": "19:00", "chi_phi_vnd_km": "12000",
                   "chi_phi_co_dinh_vnd": "800000"}
# (mã, tên, khu vực, vĩ độ, kinh độ, kg, m3, phút dỡ, bắt đầu, hạn chót)
DEFAULT_ORDERS = [
    ("D01", "Metro An Phú", "TP. Thủ Đức", "10.8022968922523", "106.7430916204482", 545.3, 2.11, 28, "10:00", "16:00"),
    ("D02", "Chợ Bến Thành", "Quận 1", "10.7726538062566", "106.6980422534495", 309.4, 0.62, 19, "07:00", "10:00"),
    ("D03", "Landmark 81", "Bình Thạnh", "10.7962905866861", "106.7234967912236", 286.6, 0.87, 26, "09:00", "15:00"),
    ("D04", "Aeon Tân Phú", "Tân Phú", "10.80183610285794", "106.6174280399574", 411.6, 1.72, 19, "07:00", "12:00"),
    ("D05", "Crescent Mall", "Quận 7", "10.72870455819639", "106.7188057118523", 317.9, 1.47, 10, "12:00", "17:00"),
    ("D06", "Gigamall", "TP. Thủ Đức", "10.82801225659217", "106.7214496399577", 287.4, 1.08, 23, "10:00", "13:00"),
    ("D07", "GO! Gò Vấp", "Gò Vấp", "10.82605016075397", "106.6801035669425", 343.3, 1.46, 22, "12:00", "18:00"),
    ("D08", "Bệnh viện Chợ Rẫy", "Quận 5", "10.75801215320188", "106.6595238246136", 349.4, 0.73, 11, "08:00", "12:00"),
    ("D09", "Chợ Phú Định", "Quận 8", "10.71998637982251", "106.6231008804339", 580.6, 2.07, 25, "07:00", "13:00"),
    ("D10", "Sân bay Tân Sơn Nhất", "Tân Bình", "10.81148209872419", "106.6559831838512", 305.2, 0.88, 11, "09:00", "12:00"),
]

# D11-D28: (tên, khu vực, vĩ độ, kinh độ, kiểu, same_as)
#   kiểu: "n" bình thường | "b" nhẹ nhưng cồng kềnh.   same_as: lấy toạ độ của đơn đã có (cùng địa điểm,
#   mã đơn riêng). Toạ độ là XẤP XỈ của địa điểm công khai, chờ TV4 xác minh trên bản đồ.
NEW_PLACES = [
    ("Vincom Center Đồng Khởi", "Quận 1", 10.7781, 106.7020, "n", None),            # D11
    ("Chợ Bình Tây", "Quận 6", 10.7506, 106.6503, "n", None),                       # D12
    ("Đầm Sen", "Quận 11", 10.7633, 106.6361, "n", None),                           # D13
    ("Vạn Hạnh Mall", "Quận 10", 10.7708, 106.6702, "b", None),                     # D14
    ("SC VivoCity", "Quận 7", 10.7298, 106.7058, "n", None),                        # D15
    ("Bệnh viện Nhi Đồng 1", "Quận 10", 10.7686, 106.6773, "n", None),              # D16
    ("Đại học Bách khoa TP.HCM", "Quận 10", 10.7731, 106.6600, "n", None),          # D17
    ("Thảo Cầm Viên Sài Gòn", "Quận 1", 10.7876, 106.7053, "n", None),              # D18
    ("Lotte Mart Quận 7", "Quận 7", 10.7413, 106.7022, "n", None),                  # D19
    ("Etown Cộng Hòa", "Tân Bình", 10.8010, 106.6531, "b", None),                   # D20
    ("Công viên Gia Định", "Phú Nhuận", 10.8105, 106.6775, "n", None),              # D21
    ("Chợ Thủ Đức", "TP. Thủ Đức", 10.8497, 106.7536, "n", None),                   # D22
    ("Suối Tiên", "TP. Thủ Đức", 10.8654, 106.8026, "b", None),                     # D23
    ("Landmark 81 - Khu văn phòng", None, None, None, "n", "D03"),                  # D24 cùng điểm D03
    ("Chợ Bến Thành - Cổng Nam", None, None, None, "n", "D02"),                     # D25 cùng điểm D02
    ("Co.opmart Nguyễn Đình Chiểu", "Quận 3", 10.7840, 106.6870, "n", None),        # D26
    ("Dinh Độc Lập", "Quận 1", 10.7770, 106.6955, "n", None),                       # D27
    ("Cảng Cát Lái", "TP. Thủ Đức", 10.7600, 106.7970, "n", None),                  # D28
]


class BaseDataError(Exception):
    """Dữ liệu gốc không dùng được - dừng để nhóm xử lý, không tự đoán."""


# ======================================================================================
# Đọc dữ liệu gốc
# ======================================================================================
def _read(path, name):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        raise BaseDataError(f"{path.name} rỗng")
    header = [h.strip() for h in rows[0]]
    if header != SCHEMA[name]:
        raise BaseDataError(
            f"Cột của {path.name} khác schema chuẩn.\n  File gốc : {header}\n  Schema   : {SCHEMA[name]}\n"
            "  Generator KHÔNG tự đổi tên cột. Nếu nhóm đã thống nhất đổi cột, hãy cập nhật SCHEMA trong "
            "validate_data.py (và CONFIG/code sinh dữ liệu) cho khớp; nếu chưa thì sửa file gốc về đúng cột.")
    return [dict(zip(header, [c.strip() for c in r])) for r in rows[1:] if any(c.strip() for c in r)]


def load_base(base_dir):
    """Trả về (depots[list[list[str]]], vehicle_template[dict], orig_orders[list[dict]], ghi_chú[list])."""
    notes = []
    base_dir = Path(base_dir)
    paths = {n: base_dir / f"{n}.csv" for n in SCHEMA}

    # --- kho
    if paths["depots"].is_file():
        rows = _read(paths["depots"], "depots")
        depots = [[r[c] for c in SCHEMA["depots"]] for r in rows]
        notes.append(f"kho: đọc {paths['depots'].name} ({len(depots)} kho)")
    else:
        depots = [r[:] for r in DEFAULT_DEPOTS]
        notes.append("kho: dùng bộ nhúng sẵn (không thấy depots.csv gốc)")
    if [d[0] for d in depots] != ["K01", "K02"]:
        raise BaseDataError(
            f"Generator hiện thiết kế cho đúng 2 kho K01, K02 (các kịch bản, nhất là S04, dùng hai mã này); "
            f"depots.csv có {[d[0] for d in depots]}. Cần mở rộng CONFIG/code trước khi thêm kho.")

    # --- xe mẫu
    if paths["vehicles"].is_file():
        rows = _read(paths["vehicles"], "vehicles")
        if not rows:
            raise BaseDataError("vehicles.csv không có dòng dữ liệu")
        vtpl = {k: rows[0][k] for k in DEFAULT_VEHICLE}
        notes.append(f"xe: lấy thông số xe mẫu từ dòng đầu {paths['vehicles'].name} ({rows[0]['ma_xe']})")
    else:
        vtpl = dict(DEFAULT_VEHICLE)
        notes.append("xe: dùng bộ nhúng sẵn (không thấy vehicles.csv gốc)")

    # --- đơn gốc D01-D10
    if paths["orders"].is_file():
        rows = _read(paths["orders"], "orders")
        ids = [r["ma_don"] for r in rows[:10]]
        if ids != [f"D{i:02d}" for i in range(1, 11)]:
            raise BaseDataError(
                f"{paths['orders'].name}: 10 dòng đầu phải là D01..D10 theo thứ tự (hiện là {ids}). "
                "Generator giữ nguyên D01-D10 của file gốc làm nền cho S01.")
        orig = []
        for r in rows[:10]:
            try:
                orig.append((r["ma_don"], r["ten_khach_hang"], r["dia_chi"], r["vi_do"], r["kinh_do"],
                             float(r["khoi_luong_kg"]), float(r["the_tich_m3"]),
                             int(r["thoi_gian_phuc_vu_phut"]), r["gio_bat_dau"], r["gio_ket_thuc"]))
            except ValueError as e:
                raise BaseDataError(f"{paths['orders'].name}: đơn {r['ma_don']} có giá trị sai ({e}). "
                                    "Chạy validate_data.py để xem lỗi chi tiết.")
        notes.append(f"đơn: D01-D10 đọc từ {paths['orders'].name}")
        if len(rows) > 10:
            notes.append(f"LƯU Ý: {paths['orders'].name} có {len(rows)} dòng; kịch bản chỉ dùng 10 dòng đầu")
    else:
        orig = list(DEFAULT_ORDERS)
        notes.append("đơn: dùng D01-D10 nhúng sẵn (không thấy orders.csv gốc)")
    return depots, vtpl, orig, notes


# ======================================================================================
# Sinh dữ liệu
# ======================================================================================
def hm(minutes):
    return f"{int(minutes) // 60:02d}:{int(minutes) % 60:02d}"


def to_min(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def base_pool(orig, seed):
    """28 điểm giao với số liệu của S01. D01-D10 từ dữ liệu gốc, D11-D28 sinh bằng seed cố định."""
    rng = random.Random(seed)
    pool = []
    for ma, ten, kv, lat, lon, kg, m3, svc, st, en in orig:
        pool.append(dict(ma=ma, ten=ten, kv=kv, lat=lat, lon=lon, kg=kg, m3=m3, svc=svc,
                         st=st, en=en, kieu="n"))
    by_id = {p["ma"]: p for p in pool}
    for j, (ten, kv, lat, lon, kieu, same_as) in enumerate(NEW_PLACES, start=11):
        if same_as:
            ref = by_id[same_as]
            kv, lat, lon = ref["kv"], ref["lat"], ref["lon"]
        else:
            lat, lon = str(lat), str(lon)
        if kieu == "b":                                   # nhẹ nhưng cồng kềnh
            kg = round(rng.uniform(70, 130), 1)
            m3 = round(rng.uniform(6.5, 9.5), 2)
        else:
            kg = round(rng.uniform(150, 330), 1)
            m3 = round(kg / 1000 * rng.uniform(2.0, 4.5), 2)
        svc = rng.choice([8, 10, 12, 15, 18, 20, 22, 25])
        st = rng.choice([420, 480, 540, 600, 660, 720, 780])        # 07:00 - 13:00
        length = rng.choice([180, 240, 300, 360])
        en = min(st + length, 18 * 60)
        p = dict(ma=f"D{j:02d}", ten=ten, kv=kv, lat=lat, lon=lon, kg=kg, m3=m3, svc=svc,
                 st=hm(st), en=hm(en), kieu=kieu)
        pool.append(p)
        by_id[p["ma"]] = p
    return pool


def make_vehicles(depots, vtpl, per_depot):
    rows, k = [], 1
    for d in depots:
        for _ in range(per_depot):
            rows.append([f"V{k:02d}", d[0]] + [vtpl[c] for c in SCHEMA["vehicles"][2:]])
            k += 1
    return rows


def order_row(o, kho="K01;K02"):
    return [o["ma"], o["ten"], o["kv"], o["lat"], o["lon"], o["kg"], o["m3"], o["svc"],
            o["st"], o["en"], kho]


def scale(o, f):
    """Nhân khối lượng/thể tích với f (bỏ qua hàng cồng kềnh)."""
    o = dict(o)
    if o["kieu"] == "n":
        o["kg"] = round(o["kg"] * f, 1)
        o["m3"] = round(o["m3"] * f, 2)
    return o


def solve_scale(base, target_kg):
    tot = sum(o["kg"] for o in base if o["kieu"] == "n")
    fixed = sum(o["kg"] for o in base if o["kieu"] != "n")
    return (target_kg - fixed) / tot


def s01(pool, depots, vtpl, cfg, seed):
    orders = [dict(o) for o in pool[:cfg["n_orders"]]]
    return make_vehicles(depots, vtpl, cfg["vehicles_per_depot"]), [order_row(o) for o in orders]


def s02(pool, depots, vtpl, cfg, seed):
    base = [dict(o) for o in pool[:cfg["n_orders"]]]
    f = solve_scale(base, cfg["target_kg"])
    return (make_vehicles(depots, vtpl, cfg["vehicles_per_depot"]),
            [order_row(scale(o, f)) for o in base])


def s03(pool, depots, vtpl, cfg, seed):
    rng = random.Random(seed + 3)
    orders = []
    for o in (dict(p) for p in pool[:cfg["n_orders"]]):
        st = rng.choice(cfg["start_choices"])
        length = o["svc"] + rng.choice(cfg["slack_choices"])
        length = (length + 4) // 5 * 5
        o["st"], o["en"] = hm(st), hm(st + length)
        orders.append(o)
    return (make_vehicles(depots, vtpl, cfg["vehicles_per_depot"]), [order_row(o) for o in orders])


def s04(pool, depots, vtpl, cfg, seed):
    k01, k02 = set(cfg["only_k01"]), set(cfg["only_k02"])
    rows = []
    for o in (dict(p) for p in pool[:cfg["n_orders"]]):
        kho = "K01" if o["ma"] in k01 else "K02" if o["ma"] in k02 else "K01;K02"
        rows.append(order_row(o, kho))
    return make_vehicles(depots, vtpl, cfg["vehicles_per_depot"]), rows


def s05(pool, depots, vtpl, cfg, seed):
    base = [dict(o) for o in pool[:cfg["n_orders"]]]
    f = solve_scale(base, cfg["target_kg"])
    orders = [scale(o, f) for o in base]
    ma, kg, m3 = cfg["oversized"]
    for o in orders:
        if o["ma"] == ma:
            o["kg"], o["m3"] = kg, m3
    for ma, kg, m3 in cfg["bulky"]:
        for o in orders:
            if o["ma"] == ma:
                o["kg"], o["m3"], o["kieu"] = kg, m3, "b"
    return make_vehicles(depots, vtpl, cfg["vehicles_per_depot"]), [order_row(o) for o in orders]


# (mã, hàm, tên, mục đích, đặc điểm (format theo metrics), kết quả mong đợi, validator mong đợi)
SCENARIOS = [
    ("S01", s01, "Bình thường",
     "Dữ liệu cơ sở mở rộng: đơn phân bố tương đối đều, hạn giao hợp lý, đội xe đủ sức chứa.",
     "{n} đơn (D01-D10 giữ nguyên bản gốc); {dup} đơn dùng chung địa điểm (mỗi đơn mã riêng); "
     "{bulky} đơn nhẹ nhưng cồng kềnh; mọi đơn phục vụ được từ K01 và K02; {nveh} xe.",
     "Phân được toàn bộ {n} đơn, không trễ hạn; cần tối thiểu {minveh} xe theo tải/thể tích (phương án thử giao đủ bằng {plan_used} xe).",
     "Không lỗi; không cảnh báo khả thi."),
    ("S02", s02, "Nhu cầu cao",
     "Nhiều hàng, buộc phải cân nhắc dùng thêm xe để chở hết.",
     "{n} đơn, tổng {kg:,.0f} kg cần tối thiểu {minveh} xe (mỗi xe {maxkg:,.0f} kg); đội xe có {nveh} xe "
     "({per} xe/kho); đơn cồng kềnh giữ nguyên.",
     "Phân được toàn bộ {n} đơn; phải dùng từ {minveh} xe trở lên (phương án thử dùng {plan_used}/{nveh} xe); chi phí cố định cao hơn S01.",
     "Không lỗi; không cảnh báo khả thi."),
    ("S03", s03, "Hạn giao gấp",
     "Nhiều đơn có khung giờ gần nhau, khó gom chuyến.",
     "{n} đơn; khung giờ hẹp (chỉ rộng hơn thời gian dỡ 40-75 phút), dồn vào 08:30-11:45; {nveh} xe ({per} xe/kho) vì với 4 xe không giao đủ được.",
     "Giao đủ được nhưng phải chạy song song nhiều xe (phương án thử cần {plan_used}/{nveh} xe, nhiều hơn S01); chi phí cao hơn S01; thuật toán yếu có thể trễ hạn hoặc bỏ sót đơn.",
     "Không lỗi; không cảnh báo khả thi (mỗi đơn riêng lẻ vẫn kịp nếu xuất phát sớm)."),
    ("S04", s04, "Giới hạn kho",
     "Một số đơn chỉ được phục vụ từ K01 hoặc K02.",
     "{n} đơn: {k01} đơn chỉ K01 (kho_phuc_vu = K01), {k02} đơn chỉ K02, {both} đơn cả hai (K01;K02); {nveh} xe.",
     "Giao đủ {n} đơn; mọi đơn chỉ-K01 do xe kho K01 giao, mọi đơn chỉ-K02 do xe kho K02 giao; không đơn nào bị gán sai kho.",
     "Không lỗi; không cảnh báo khả thi."),
    ("S05", s05, "Thiếu năng lực vận chuyển",
     "Dữ liệu HỢP LỆ nhưng không có phương án giao đủ hàng, để kiểm tra cơ chế cảnh báo.",
     "{n} đơn; tổng {kg:,.0f} kg vượt tải đội {nveh} xe ({capkg:,.0f} kg); {over} đơn nặng hơn tải mọi xe "
     "({over_ids}); {bulky} đơn nhẹ nhưng cồng kềnh làm căng giới hạn thể tích (tổng {m3:,.1f} m3 > {capm3:,.0f} m3).",
     "Không thể phân hết đơn: thuật toán/giao diện phải báo danh sách đơn chưa được phục vụ "
     "(chắc chắn có {over_ids}), không được báo lỗi dữ liệu.",
     "Không lỗi (ERROR = 0); có cảnh báo W_FEAS_* (đơn quá tải, tổng tải vượt đội xe)."),
]

DESC_HEADER = ["ma_kich_ban", "ten_kich_ban", "muc_dich", "dac_diem_du_lieu", "so_don", "so_kho",
               "so_xe", "tong_khoi_luong_don_kg", "tong_tai_trong_doi_xe_kg", "tong_the_tich_don_m3",
               "tong_the_tich_doi_xe_m3", "so_xe_toi_thieu_uoc_tinh", "so_don_chi_K01",
               "so_don_chi_K02", "so_don_ca_hai_kho", "so_don_cung_dia_diem", "so_don_cong_kenh",
               "thu_muc", "ket_qua_mong_doi", "ket_qua_validator_mong_doi"]


# ======================================================================================
# Chỉ số và kiểm tra thiết kế
# ======================================================================================
def metrics(depots, vehs, orders):
    kg = sum(o[5] for o in orders)
    m3 = sum(o[6] for o in orders)
    capkg = sum(float(v[2]) for v in vehs)
    capm3 = sum(float(v[3]) for v in vehs)
    maxkg = max(float(v[2]) for v in vehs)
    maxm3 = max(float(v[3]) for v in vehs)
    loc_count = {}
    for o in orders:
        loc_count[(o[3], o[4])] = loc_count.get((o[3], o[4]), 0) + 1
    over = [o[0] for o in orders if o[5] > maxkg or o[6] > maxm3]
    return dict(
        n=len(orders), nkho=len(depots), nveh=len(vehs), kg=kg, m3=m3, capkg=capkg, capm3=capm3,
        maxkg=maxkg, maxm3=maxm3, per=len(vehs) // max(1, len(depots)),
        minveh=max(math.ceil(kg / maxkg), math.ceil(m3 / maxm3)),
        k01=sum(1 for o in orders if o[10] == "K01"),
        k02=sum(1 for o in orders if o[10] == "K02"),
        both=sum(1 for o in orders if o[10] == "K01;K02"),
        dup=sum(c for c in loc_count.values() if c > 1),
        bulky=sum(1 for o in orders if o[5] > 0 and o[6] / o[5] * 1000 >= BULKY_M3_PER_TON),
        over=len(over), over_ids=", ".join(over) if over else "không có",
    )


def verify_design(code, cfg, depots, vehs, orders, m):
    """Mỗi kịch bản phải còn đúng mục đích thiết kế. Trả về danh sách lỗi (rỗng = đạt)."""
    bad = []
    ids = [o[0] for o in orders]
    if len(set(ids)) != len(ids):
        bad.append("mã đơn bị trùng")
    if not 20 <= m["n"] <= 30:
        bad.append(f"số đơn {m['n']} ngoài khoảng 20-30 theo yêu cầu")
    if m["nkho"] != 2:
        bad.append(f"cần đúng 2 kho, đang có {m['nkho']}")
    if not 4 <= m["nveh"] <= 6:
        bad.append(f"số xe {m['nveh']} ngoài khoảng 4-6 theo yêu cầu")
    dep = {d[0] for d in depots}
    for o in orders:
        if not set(o[10].split(";")) <= dep:
            bad.append(f"đơn {o[0]} tham chiếu kho không tồn tại ({o[10]})")
    if code == "S01":
        if m["kg"] > 0.85 * m["capkg"] or m["m3"] > 0.85 * m["capm3"]:
            bad.append("S01 phải thoải mái về sức chứa (<= 85% tải và thể tích đội xe)")
        if m["k01"] or m["k02"]:
            bad.append("S01: mọi đơn phải phục vụ được từ cả hai kho")
        if m["dup"] < 2:
            bad.append("S01 cần có đơn cùng địa điểm (mã đơn riêng)")
        if m["bulky"] < 1:
            bad.append("S01 cần có đơn nhẹ nhưng cồng kềnh")
    elif code == "S02":
        if not 5 <= m["minveh"] <= m["nveh"]:
            bad.append(f"S02 phải cần >= 5 xe nhưng không vượt đội xe: cần tối thiểu {m['minveh']}, có {m['nveh']}")
    elif code == "S03":
        for o in orders:
            st, en = to_min(o[8]), to_min(o[9])
            if st < 8 * 60 + 30 or en > 12 * 60:
                bad.append(f"S03: đơn {o[0]} khung {o[8]}-{o[9]} ngoài 08:30-12:00")
            if en - st - o[7] > 80:
                bad.append(f"S03: đơn {o[0]} khung giờ không đủ gấp (dư {en - st - o[7]} phút)")
    elif code == "S04":
        if (m["k01"], m["k02"]) != (len(cfg["only_k01"]), len(cfg["only_k02"])) or m["both"] < 1:
            bad.append(f"S04: số đơn theo kho lệch cấu hình (K01={m['k01']}, K02={m['k02']}, cả hai={m['both']})")
        for depot in ("K01", "K02"):
            cap = sum(float(v[2]) for v in vehs if v[1] == depot)
            need = sum(o[5] for o in orders if o[10] == depot)
            if need > cap:
                bad.append(f"S04: đơn chỉ-{depot} nặng {need:.1f} kg vượt tải xe kho {depot} ({cap:g} kg); "
                           "S04 phải khả thi, chỉ S05 được thiếu năng lực")
    elif code == "S05":
        if m["kg"] <= m["capkg"]:
            bad.append("S05: tổng khối lượng phải VƯỢT tải đội xe")
        if m["m3"] <= m["capm3"]:
            bad.append("S05: tổng thể tích phải VƯỢT thể tích đội xe")
        if m["over"] < 1:
            bad.append("S05: cần ít nhất 1 đơn nặng/cồng kềnh hơn mọi xe")
        if m["bulky"] < 3:
            bad.append("S05: cần >= 3 đơn nhẹ nhưng cồng kềnh")
    return bad


# ======================================================================================
# Kiểm tra nhanh "có phương án giao khả thi không" (heuristic - KHÔNG phải thuật toán của nhóm)
# ======================================================================================
SPEED_KMH, ROAD_FACTOR = 30.0, 1.3          # cùng giả định với validate_data.py
PLAN_TRIES = 150


def _hav(a, b):
    r = 6371.0088
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def try_plan(depots, vehs, orders, seed, tries=PLAN_TRIES):
    """Chèn đơn theo thứ tự ngẫu nhiên vào tuyến xe (mỗi xe một chuyến/ca) để xem có giao đủ được không.
    Trả về (giao_đủ, số đơn giao nhiều nhất tìm được, số xe dùng ít nhất khi giao đủ)."""
    dep = {d[0]: (float(d[3]), float(d[4])) for d in depots}
    ords = [dict(ma=o[0], pos=(float(o[3]), float(o[4])), kg=float(o[5]), m3=float(o[6]), sv=int(o[7]),
                 st=to_min(o[8]), en=to_min(o[9]), ok=set(o[10].split(";"))) for o in orders]
    vs = [dict(depot=v[1], kg=float(v[2]), m3=float(v[3]), s=to_min(v[4]), e=to_min(v[5])) for v in vehs]

    def tt(a, b):
        return _hav(a, b) * ROAD_FACTOR / SPEED_KMH * 60

    def route_ok(v, seq):
        t, pos = v["s"], dep[v["depot"]]
        for o in seq:
            t = max(t + tt(pos, o["pos"]), o["st"]) + o["sv"]
            if t > o["en"]:
                return False
            pos = o["pos"]
        return t + tt(pos, dep[v["depot"]]) <= v["e"]

    def dist(v, seq):
        pts = [dep[v["depot"]]] + [o["pos"] for o in seq] + [dep[v["depot"]]]
        return sum(_hav(pts[i], pts[i + 1]) for i in range(len(pts) - 1))

    rng = random.Random(seed + 99)
    best_assigned, best_used = 0, None
    for k in range(tries):
        order = ords[:]
        if k == 0:
            order.sort(key=lambda o: o["en"])                  # lần đầu: ưu tiên hạn gấp
        elif k == 1:
            order.sort(key=lambda o: -o["kg"])                 # lần hai: đơn nặng trước
        else:
            rng.shuffle(order)
        routes = [[] for _ in vs]
        assigned = 0
        for o in order:
            best = None
            for vi, v in enumerate(vs):
                if v["depot"] not in o["ok"]:
                    continue
                seq = routes[vi]
                if sum(x["kg"] for x in seq) + o["kg"] > v["kg"] or sum(x["m3"] for x in seq) + o["m3"] > v["m3"]:
                    continue
                for pos in range(len(seq) + 1):
                    cand = seq[:pos] + [o] + seq[pos:]
                    if route_ok(v, cand):
                        add = dist(v, cand) - dist(v, seq)
                        if best is None or add < best[0]:
                            best = (add, vi, cand)
            if best:
                routes[best[1]] = best[2]
                assigned += 1
        used = sum(1 for r in routes if r)
        if assigned > best_assigned:
            best_assigned = assigned
        if assigned == len(ords) and (best_used is None or used < best_used):
            best_used = used
    return best_used is not None, best_assigned, best_used


# ======================================================================================
# Xuất file
# ======================================================================================
def render_csv(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return ("\ufeff" + buf.getvalue()).encode("utf-8")       # UTF-8 có BOM, dấu thập phân là chấm


def build_all(base_dir, seed, out_dir):
    """Sinh toàn bộ trong bộ nhớ. Trả về (files{Path: bytes}, info[list], ghi_chú)."""
    depots, vtpl, orig, notes = load_base(base_dir)
    pool = base_pool(orig, seed)
    files, info, desc = {}, [], []
    for code, fn, ten, mucdich, dacdiem, ketqua, vld in SCENARIOS:
        cfg = CONFIG[code]
        vehs, orders = fn(pool, depots, vtpl, cfg, seed)
        m = metrics(depots, vehs, orders)
        fails = verify_design(code, cfg, depots, vehs, orders, m)
        full, assigned, used = try_plan(depots, vehs, orders, seed)
        m["plan_full"], m["plan_assigned"], m["plan_used"] = full, assigned, used
        if code != "S05" and not full:
            fails.append(f"{code}: heuristic chỉ giao được {assigned}/{m['n']} đơn - kịch bản này phải khả thi "
                         "(nới hạn giao/thêm xe trong CONFIG)")
        if code == "S05" and full:
            fails.append("S05: heuristic lại tìm được phương án giao đủ - kịch bản mất tính thiếu năng lực")
        d = Path(out_dir) / code
        files[d / "depots.csv"] = render_csv(SCHEMA["depots"], depots)
        files[d / "vehicles.csv"] = render_csv(SCHEMA["vehicles"], vehs)
        files[d / "orders.csv"] = render_csv(SCHEMA["orders"], orders)
        rel = d.relative_to(HERE).as_posix() if HERE in d.parents else d.as_posix()
        desc.append([code, ten, mucdich, dacdiem.format(**m), m["n"], m["nkho"], m["nveh"],
                     round(m["kg"], 1), round(m["capkg"]), round(m["m3"], 2), round(m["capm3"]),
                     m["minveh"], m["k01"], m["k02"], m["both"], m["dup"], m["bulky"], rel,
                     ketqua.format(**m), vld])
        info.append(dict(code=code, m=m, fails=fails, dir=d))
    files[Path(out_dir) / "scenario_description.csv"] = render_csv(DESC_HEADER, desc)
    return files, info, notes


def run_validator(info):
    """Chạy validate_data.py cho từng kịch bản; trả về danh sách lỗi thiết kế/kiểm tra."""
    problems = []
    if VD is None:
        return ["(bỏ qua) không import được validate_data.py"], []
    rows = []
    for it in info:
        issues = VD.validate_folder(it["dir"], it["code"])
        errs = [i for i in issues if i.level == "ERROR"]
        feas = [i for i in issues if i.code.startswith("W_FEAS")]
        other = [i for i in issues if i.level == "WARNING" and not i.code.startswith("W_FEAS")]
        rows.append((it["code"], len(errs), len(feas), len(other)))
        for i in errs:
            problems.append(f"{it['code']}: ERROR {i.file} dòng {i.line} {i.column}: {i.message}")
        for i in other:
            problems.append(f"{it['code']}: cảnh báo ngoài dự kiến {i.code}: {i.message}")
        if it["code"] == "S05":
            if not any(i.code == "W_FEAS_ORDER_TOO_HEAVY" for i in feas):
                problems.append("S05: validator không phát hiện đơn nặng hơn mọi xe - kịch bản mất tác dụng")
        elif feas:
            problems.append(f"{it['code']}: có cảnh báo khả thi {sorted({i.code for i in feas})} "
                            "nhưng kịch bản này phải khả thi")
    return problems, rows


# ======================================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description="Sinh dữ liệu mở rộng và kịch bản S01-S05.")
    ap.add_argument("--base-dir", default=str(HERE), help="thư mục chứa depots/vehicles/orders.csv gốc")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT), help="thư mục ghi kịch bản")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED, help="seed ngẫu nhiên (mặc định cố định)")
    ap.add_argument("--only", help="chỉ ghi các kịch bản này, vd S03,S05")
    ap.add_argument("--check", action="store_true", help="chỉ so sánh với file trên đĩa, không ghi")
    ap.add_argument("--list", action="store_true", help="liệt kê kịch bản rồi thoát")
    ap.add_argument("--no-validate", action="store_true", help="bỏ bước chạy validate_data.py")
    args = ap.parse_args(argv)

    if args.list:
        for code, _, ten, mucdich, *_ in SCENARIOS:
            print(f"{code}  {ten}: {mucdich}")
        return 0

    out_dir = Path(args.out_dir).resolve()
    base_dir = Path(args.base_dir).resolve()
    if out_dir == base_dir:
        print("Từ chối: --out-dir trùng thư mục dữ liệu gốc. Kịch bản phải nằm ở thư mục riêng "
              "(mặc định data/scenarios) để không ghi đè dữ liệu gốc.", file=sys.stderr)
        return 2
    only = None
    if args.only:
        only = {s.strip().upper() for s in args.only.split(",") if s.strip()}
        unknown = only - {s[0] for s in SCENARIOS}
        if unknown:
            print(f"Kịch bản không tồn tại: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2

    try:
        files, info, notes = build_all(base_dir, args.seed, out_dir)
    except BaseDataError as e:
        print(f"LỖI DỮ LIỆU GỐC: {e}", file=sys.stderr)
        return 2

    print(f"Seed = {args.seed}")
    for n in notes:
        print(f"  - {n}")

    # --- kiểm tra thiết kế
    failed = False
    for it in info:
        for msg in it["fails"]:
            print(f"[THIẾT KẾ SAI] {it['code']}: {msg}", file=sys.stderr)
            failed = True
    if failed:
        print("Dừng: tham số trong CONFIG làm kịch bản không còn đúng mục đích. Chưa ghi file nào.",
              file=sys.stderr)
        return 1

    # --- chế độ so sánh
    if args.check:
        diff = []
        for path, data in files.items():
            if not path.is_file():
                diff.append(f"thiếu: {path}")
            elif path.read_bytes() != data:
                diff.append(f"khác : {path}")
        if diff:
            print("Dữ liệu trên đĩa KHÁC kết quả sinh từ script:")
            for d in diff:
                print("  " + d)
            print("Chạy lại `python generate_scenarios.py` để đồng bộ (hoặc kiểm tra xem ai sửa tay file).")
            return 1
        print(f"Khớp hoàn toàn: {len(files)} file trên đĩa giống kết quả sinh từ script.")
        return 0

    # --- ghi file
    wrote = same = 0
    for path, data in sorted(files.items()):
        is_scen_file = path.name != "scenario_description.csv"
        if only and is_scen_file and path.parent.name not in only:
            continue
        if only and not is_scen_file:
            continue                      # đã chọn một phần: không đụng scenario_description.csv
        if path.is_file() and path.read_bytes() == data:
            same += 1
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        wrote += 1
    print(f"Đã ghi {wrote} file, {same} file không đổi. Thư mục: {out_dir}")

    print(f"\n{'KB':4s} {'đơn':>4s} {'xe':>3s} {'kg đơn / tải xe':>17s} {'m3 đơn / thể tích xe':>22s}  "
          f"{'xe tối thiểu':>12s}  phương án thử (heuristic)")
    for it in info:
        m = it["m"]
        plan = (f"giao đủ {m['n']}/{m['n']} đơn bằng {m['plan_used']} xe" if m["plan_full"]
                else f"không giao đủ: tối đa {m['plan_assigned']}/{m['n']} đơn")
        print(f"{it['code']:4s} {m['n']:4d} {m['nveh']:3d} {m['kg']:8.1f}/{m['capkg']:<8.0f} "
              f"{m['m3']:9.2f}/{m['capm3']:<10.0f}  {m['minveh']:12d}  {plan}")

    # --- tự kiểm tra bằng validator
    if not args.no_validate:
        sel = [it for it in info if not only or it["code"] in only]
        problems, rows = run_validator(sel)
        print("\nKiểm tra bằng validate_data.py:")
        for code, e, fz, o in rows:
            print(f"  {code}: ERROR={e}  cảnh báo khả thi={fz}  cảnh báo khác={o}")
        if problems:
            for p in problems:
                print(f"[KIỂM TRA THẤT BẠI] {p}", file=sys.stderr)
            return 1
        print("  -> tất cả kịch bản đúng thiết kế và không có lỗi dữ liệu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
