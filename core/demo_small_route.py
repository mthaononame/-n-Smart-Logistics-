#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demo_small_route.py - Minh hoạ ĐIỀU KIỆN HOÀN THÀNH của TV4
===========================================================
"Thành viên 2 có thể dùng dữ liệu để tính quãng đường và thời gian của một tuyến giao hàng nhỏ."

Script này lấy 1 xe + 1 dãy điểm giao, rồi tính:
  * tổng km, thời gian di chuyển (từ travel_matrix.csv);
  * giờ đến / chờ / bắt đầu dỡ / xong từng điểm, so với hạn giao (quy ước trong giai_thich_cot.csv);
  * kiểm tra tải trọng, thể tích, ca làm việc, kho phục vụ;
  * chi phí mô hình = chi_phi_co_dinh + chi_phi_vnd_km x km.

ĐÂY CHỈ LÀ BỘ KIỂM TRA MỘT TUYẾN CHO TRƯỚC - không phải thuật toán tối ưu (việc của TV2).

Ví dụ:
    python demo_small_route.py
    python demo_small_route.py --vehicle V03 --route D01,D06 --depart 08:30
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

import pandas as pd

from travel_lookup import DEFAULT_LOCATIONS_CSV, DEFAULT_MATRIX_CSV, ENCODING, TravelMatrix

HERE = Path(__file__).resolve().parent


def hhmm_to_s(text: str) -> int:
    h, m = text.strip().split(":")
    return int(h) * 3600 + int(m) * 60


def s_to_hhmm(sec: float) -> str:
    total_min = int(round(sec / 60.0))
    return f"{total_min // 60:02d}:{total_min % 60:02d}"


def fmt_vnd(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def evaluate_route(tm: TravelMatrix, vehicle: dict, orders: pd.DataFrame, route: Sequence[str],
                   depart_s: Optional[int] = None) -> dict:
    """Đánh giá 1 tuyến: kho của xe -> các điểm giao theo thứ tự -> về kho.

    vehicle: dict có ma_xe, ma_kho_quan_ly, tai_trong_kg, the_tich_m3, gio_bat_dau_ca, gio_ket_thuc_ca,
             chi_phi_vnd_km, chi_phi_co_dinh_vnd (chuỗi hoặc số).
    orders:  DataFrame index = ma_don với các cột của orders.csv.

    Quy ước thời gian (giai_thich_cot.csv):
      - xe đến sớm hơn gio_bat_dau thì CHỜ đến gio_bat_dau mới dỡ;
      - phải dỡ XONG (bắt đầu dỡ + thoi_gian_phuc_vu) <= gio_ket_thuc;
      - xe phải về kho trước gio_ket_thuc_ca.
    """
    depot = vehicle["ma_kho_quan_ly"]
    shift_start = hhmm_to_s(vehicle["gio_bat_dau_ca"])
    shift_end = hhmm_to_s(vehicle["gio_ket_thuc_ca"])
    t = shift_start if depart_s is None else depart_s
    if t < shift_start:
        raise ValueError("Giờ xuất phát sớm hơn giờ bắt đầu ca của xe.")
    depart = t

    unknown = [r for r in route if r not in orders.index]
    if unknown:
        raise KeyError(f"Mã điểm giao không có trong orders.csv: {unknown}")

    stops = []
    prev = depot
    total_m = 0
    total_drive_s = 0
    total_wait_s = 0
    total_service_s = 0
    load_kg = 0.0
    load_m3 = 0.0
    notes = []

    for code in route:
        o = orders.loc[code]
        leg_s = tm.time_s(prev, code)
        total_m += tm.dist_m(prev, code)
        total_drive_s += leg_s
        arrive = t + leg_s
        window_open = hhmm_to_s(o["gio_bat_dau"])
        deadline = hhmm_to_s(o["gio_ket_thuc"])
        start = max(arrive, window_open)
        wait = start - arrive
        service = int(float(o["thoi_gian_phuc_vu_phut"]) * 60)
        finish = start + service
        ok = finish <= deadline
        served = [k.strip() for k in str(o["kho_phuc_vu"]).split(";")]
        if depot not in served:
            notes.append(f"{code}: kho {depot} KHÔNG nằm trong kho_phuc_vu ({served}).")
        if not ok:
            notes.append(f"{code}: TRỄ HẠN - xong lúc {s_to_hhmm(finish)} > hạn {s_to_hhmm(deadline)} "
                         f"(trễ {(finish - deadline) / 60:.1f} phút).")
        stops.append({"ma": code, "ten": o["ten_khach_hang"], "den": arrive, "cho": wait, "bat_dau": start,
                      "xong": finish, "han": deadline, "dung_han": ok})
        total_wait_s += wait
        total_service_s += service
        load_kg += float(o["khoi_luong_kg"])
        load_m3 += float(o["the_tich_m3"])
        t = finish
        prev = code

    # về kho
    total_m += tm.dist_m(prev, depot)
    leg_back = tm.time_s(prev, depot)
    total_drive_s += leg_back
    back = t + leg_back
    in_shift = back <= shift_end
    if not in_shift:
        notes.append(f"Về kho lúc {s_to_hhmm(back)} > hết ca {s_to_hhmm(shift_end)}.")

    cap_kg = float(vehicle["tai_trong_kg"])
    cap_m3 = float(vehicle["the_tich_m3"])
    if load_kg > cap_kg:
        notes.append(f"QUÁ TẢI: {load_kg:.1f} kg > {cap_kg:.0f} kg.")
    if load_m3 > cap_m3:
        notes.append(f"QUÁ THỂ TÍCH: {load_m3:.2f} m3 > {cap_m3:.2f} m3.")

    km = total_m / 1000.0
    used = len(route) > 0
    cost = (float(vehicle["chi_phi_co_dinh_vnd"]) + float(vehicle["chi_phi_vnd_km"]) * km) if used else 0.0
    feasible = all(s["dung_han"] for s in stops) and in_shift and load_kg <= cap_kg and load_m3 <= cap_m3 \
        and not any("KHÔNG nằm trong kho_phuc_vu" in n for n in notes)

    return {
        "ma_xe": vehicle["ma_xe"], "kho": depot, "route": [depot, *route, depot], "stops": stops,
        "xuat_phat": depart, "ve_kho": back, "km": km,
        "di_chuyen_s": total_drive_s, "cho_s": total_wait_s, "do_hang_s": total_service_s,
        "tai_kg": load_kg, "the_tich_m3": load_m3, "chi_phi_vnd": cost,
        "kha_thi": feasible, "ghi_chu": notes, "nguon_ma_tran": tm.provider,
    }


def print_report(r: dict) -> None:
    print(f"Xe {r['ma_xe']} (kho {r['kho']})  |  nguồn ma trận: {r['nguon_ma_tran']}")
    print("Tuyến: " + " -> ".join(r["route"]))
    print(f"Xuất phát kho lúc {s_to_hhmm(r['xuat_phat'])}\n")
    print(f"{'Điểm':<5}{'Tên':<24}{'Đến':>6}{'Chờ(p)':>8}{'Bắt đầu':>9}{'Xong':>7}{'Hạn':>7}  Đúng hạn")
    for s in r["stops"]:
        print(f"{s['ma']:<5}{s['ten'][:22]:<24}{s_to_hhmm(s['den']):>6}{s['cho'] / 60:>8.1f}"
              f"{s_to_hhmm(s['bat_dau']):>9}{s_to_hhmm(s['xong']):>7}{s_to_hhmm(s['han']):>7}  "
              f"{'ĐÚNG' if s['dung_han'] else 'TRỄ'}")
    print(f"\nVề kho lúc {s_to_hhmm(r['ve_kho'])}")
    print(f"Tổng quãng đường : {r['km']:.2f} km")
    print(f"Thời gian lái    : {r['di_chuyen_s'] / 60:.1f} phút | chờ {r['cho_s'] / 60:.1f} phút | "
          f"dỡ hàng {r['do_hang_s'] / 60:.1f} phút")
    print(f"Tải              : {r['tai_kg']:.1f} kg, {r['the_tich_m3']:.2f} m3")
    print(f"Chi phí mô hình  : {fmt_vnd(r['chi_phi_vnd'])} VND  (cố định + đơn giá/km x km)")
    print(f"KẾT LUẬN         : {'KHẢ THI' if r['kha_thi'] else 'KHÔNG KHẢ THI'}")
    for n in r["ghi_chu"]:
        print(f"  ! {n}")


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if reconf:
            reconf(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Tính thử một tuyến giao hàng nhỏ từ travel_matrix.csv")
    ap.add_argument("--matrix", default=str(DEFAULT_MATRIX_CSV))
    ap.add_argument("--locations", default=str(DEFAULT_LOCATIONS_CSV))
    ap.add_argument("--orders", default=str(HERE / "data" / "orders.csv"))
    ap.add_argument("--vehicles", default=str(HERE / "data" / "vehicles.csv"))
    ap.add_argument("--vehicle", default="V01")
    ap.add_argument("--route", default="D02,D03,D08", help="Các điểm giao theo thứ tự, ngăn cách bởi dấu phẩy")
    ap.add_argument("--depart", default=None, help="Giờ xuất phát HH:MM (mặc định = giờ bắt đầu ca)")
    args = ap.parse_args(argv)

    tm = TravelMatrix.from_csv(args.matrix, args.locations)
    orders = pd.read_csv(args.orders, encoding=ENCODING, dtype=str, keep_default_na=False).set_index("ma_don")
    veh = pd.read_csv(args.vehicles, encoding=ENCODING, dtype=str, keep_default_na=False).set_index("ma_xe")
    if args.vehicle not in veh.index:
        print(f"Không có xe {args.vehicle}. Hợp lệ: {veh.index.tolist()}", file=sys.stderr)
        return 2
    vehicle = {"ma_xe": args.vehicle, **veh.loc[args.vehicle].to_dict()}
    route = [x.strip() for x in args.route.split(",") if x.strip()]
    depart = hhmm_to_s(args.depart) if args.depart else None
    print_report(evaluate_route(tm, vehicle, orders, route, depart))
    return 0


if __name__ == "__main__":
    sys.exit(main())
