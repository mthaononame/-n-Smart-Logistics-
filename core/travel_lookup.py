#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
travel_lookup.py - Thư viện tra cứu ma trận đường đi (dành cho Thành viên 2 / OR-Tools)
=====================================================================================

Đọc file `output/travel_matrix.csv` + `output/locations.csv` do TV4 bàn giao và cung cấp:

  * tra cứu nhanh khoảng cách / thời gian giữa 2 địa điểm;
  * tính tổng quãng đường + thời gian lái xe của MỘT tuyến (danh sách mã địa điểm);
  * xuất ma trận số nguyên (mét, giây) để đưa thẳng vào OR-Tools.

Quy ước (khớp với giai_thich_cot.csv của dự án):
  * Mã địa điểm = mã kho (K01, K02, ...) hoặc mã đơn (D01, ..., D10).
  * Khoảng cách: mét (số nguyên) | Thời gian: giây (số nguyên).
  * Ma trận BẤT ĐỐI XỨNG: d(A->B) có thể khác d(B->A) (đường một chiều).
  * Đường chéo d(A->A) = 0 và KHÔNG nằm trong file CSV (file chỉ chứa A != B).
  * Thời gian là thời gian di chuyển ƯỚC TÍNH, KHÔNG gồm thời gian dỡ hàng
    (thoi_gian_phuc_vu_phut trong orders.csv do TV2 cộng thêm).

Chạy thử từ dòng lệnh:
    python travel_lookup.py K01 D02 D03 K01
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import pandas as pd

ENCODING = "utf-8-sig"  # CSV của dự án: UTF-8 có BOM

# ---- Tên cột (một nguồn sự thật duy nhất, build_travel_matrix.py cũng import từ đây) ----
COL_FROM = "ma_di"
COL_TO = "ma_den"
COL_DIST_M = "khoang_cach_m"
COL_TIME_S = "thoi_gian_s"
COL_DIST_KM = "khoang_cach_km"
COL_TIME_MIN = "thoi_gian_phut"
COL_SOURCE = "nguon"
MATRIX_COLUMNS = [COL_FROM, COL_TO, COL_DIST_M, COL_TIME_S, COL_DIST_KM, COL_TIME_MIN, COL_SOURCE]
LOCATION_COLUMNS = ["loc_idx", "ma_vi_tri", "loai", "ten", "dia_chi", "vi_do", "kinh_do"]

HERE = Path(__file__).resolve().parent
DEFAULT_MATRIX_CSV = HERE / "output" / "travel_matrix.csv"
DEFAULT_LOCATIONS_CSV = HERE / "output" / "locations.csv"


@dataclass(frozen=True)
class Leg:
    """Một chặng A -> B."""
    ma_di: str
    ma_den: str
    khoang_cach_km: float
    thoi_gian_phut: float


@dataclass(frozen=True)
class RouteTotals:
    """Tổng hợp của một tuyến (chỉ phần di chuyển, chưa gồm thời gian dỡ hàng)."""
    route: tuple
    legs: tuple
    khoang_cach_km: float
    thoi_gian_di_chuyen_phut: float
    khoang_cach_m: int
    thoi_gian_di_chuyen_s: int


class TravelMatrix:
    """Ma trận khoảng cách (m) và thời gian (s) giữa mọi cặp địa điểm.

    Thứ tự `ids` chính là chỉ số hàng/cột (0..n-1) - dùng làm "node index" khi đưa vào OR-Tools.
    """

    def __init__(self, ids: Sequence[str], dist_m, dur_s, *, sources=None,
                 locations: Optional[pd.DataFrame] = None, meta: Optional[dict] = None):
        self.ids = [str(i) for i in ids]
        n = len(self.ids)
        if n == 0:
            raise ValueError("Danh sách địa điểm rỗng.")
        if len(set(self.ids)) != n:
            raise ValueError("Mã địa điểm bị trùng nhau.")
        d = np.asarray(dist_m, dtype=float)
        t = np.asarray(dur_s, dtype=float)
        if d.shape != (n, n) or t.shape != (n, n):
            raise ValueError(f"Ma trận phải có kích thước {n}x{n}, nhận được {d.shape} và {t.shape}.")
        if not (np.isfinite(d).all() and np.isfinite(t).all()):
            raise ValueError("Ma trận chứa giá trị NaN/vô cực.")
        if (d < 0).any() or (t < 0).any():
            raise ValueError("Ma trận chứa giá trị âm.")
        if np.any(np.diag(d) != 0) or np.any(np.diag(t) != 0):
            raise ValueError("Đường chéo ma trận phải bằng 0.")
        self._dist_m = np.rint(d).astype(np.int64)
        self._dur_s = np.rint(t).astype(np.int64)
        self._index = {loc_id: k for k, loc_id in enumerate(self.ids)}
        self.sources = sources  # ma trận nhãn nguồn (n x n) hoặc None
        self.locations = locations
        self.meta = meta or {}

    # ------------------------------------------------------------------ nạp dữ liệu
    @classmethod
    def from_csv(cls, matrix_csv=DEFAULT_MATRIX_CSV, locations_csv=DEFAULT_LOCATIONS_CSV,
                 meta_json=None, warn_if_estimate: bool = True) -> "TravelMatrix":
        """Nạp từ travel_matrix.csv (+ locations.csv, + travel_matrix_meta.json nếu có)."""
        matrix_csv = Path(matrix_csv)
        if not matrix_csv.exists():
            raise FileNotFoundError(f"Không thấy {matrix_csv}. Hãy chạy build_travel_matrix.py trước.")
        df = pd.read_csv(matrix_csv, encoding=ENCODING,
                         dtype={COL_FROM: str, COL_TO: str, COL_SOURCE: str})
        missing_cols = [c for c in (COL_FROM, COL_TO, COL_DIST_M, COL_TIME_S) if c not in df.columns]
        if missing_cols:
            raise ValueError(f"{matrix_csv.name} thiếu cột {missing_cols}.")
        df[COL_FROM] = df[COL_FROM].str.strip()
        df[COL_TO] = df[COL_TO].str.strip()
        if df[[COL_DIST_M, COL_TIME_S]].isna().any().any():
            bad = df[df[[COL_DIST_M, COL_TIME_S]].isna().any(axis=1)].head(3)
            raise ValueError(f"{matrix_csv.name} có ô trống ở khoảng cách/thời gian, ví dụ:\n{bad}")

        # Danh sách địa điểm: ưu tiên locations.csv (có thứ tự loc_idx), nếu không thì suy ra từ ma trận
        locations = None
        locations_csv = Path(locations_csv) if locations_csv else None
        if locations_csv is not None and locations_csv.exists():
            locations = pd.read_csv(locations_csv, encoding=ENCODING,
                                    dtype={"ma_vi_tri": str, "loai": str}).sort_values("loc_idx")
            ids = locations["ma_vi_tri"].str.strip().tolist()
        else:
            ids = list(dict.fromkeys(df[COL_FROM].tolist() + df[COL_TO].tolist()))

        index = {loc_id: k for k, loc_id in enumerate(ids)}
        n = len(ids)

        # Bỏ dòng tự-đến-chính-mình (nếu có) sau khi kiểm tra phải bằng 0
        same = df[COL_FROM] == df[COL_TO]
        if same.any():
            if (df.loc[same, [COL_DIST_M, COL_TIME_S]] != 0).any().any():
                raise ValueError("Có dòng A->A với khoảng cách/thời gian khác 0.")
            df = df.loc[~same]

        if df.duplicated([COL_FROM, COL_TO]).any():
            dup = df[df.duplicated([COL_FROM, COL_TO], keep=False)].head(4)
            raise ValueError(f"Có cặp (đi, đến) bị lặp:\n{dup[[COL_FROM, COL_TO]]}")

        ii = df[COL_FROM].map(index)
        jj = df[COL_TO].map(index)
        if ii.isna().any() or jj.isna().any():
            unknown = sorted(set(df.loc[ii.isna(), COL_FROM]) | set(df.loc[jj.isna(), COL_TO]))
            raise ValueError(f"Mã địa điểm trong ma trận không có trong danh sách địa điểm: {unknown}")
        ii = ii.to_numpy(dtype=int)
        jj = jj.to_numpy(dtype=int)

        dist = np.zeros((n, n), dtype=float)
        dur = np.zeros((n, n), dtype=float)
        have = np.eye(n, dtype=bool)
        dist[ii, jj] = df[COL_DIST_M].to_numpy(dtype=float)
        dur[ii, jj] = df[COL_TIME_S].to_numpy(dtype=float)
        have[ii, jj] = True
        if not have.all():
            mi, mj = np.nonzero(~have)
            examples = [f"{ids[a]}->{ids[b]}" for a, b in list(zip(mi, mj))[:5]]
            raise ValueError(f"Thiếu {len(mi)} cặp trong ma trận, ví dụ: {examples}")

        sources = None
        if COL_SOURCE in df.columns:
            sources = np.full((n, n), "", dtype=object)
            sources[ii, jj] = df[COL_SOURCE].fillna("").to_numpy(dtype=object)

        meta_path = Path(meta_json) if meta_json else matrix_csv.with_name("travel_matrix_meta.json")
        meta = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))

        tm = cls(ids, dist, dur, sources=sources, locations=locations, meta=meta)
        if warn_if_estimate and tm.is_estimate:
            warnings.warn(
                "travel_matrix hiện là ƯỚC LƯỢNG (đường chim bay x hệ số), KHÔNG phải dữ liệu theo mạng "
                "đường. Chạy `python build_travel_matrix.py --provider osrm` để lấy dữ liệu đường thực "
                "trước khi đánh giá chính thức.", UserWarning, stacklevel=2)
        return tm

    # ------------------------------------------------------------------ thuộc tính
    @property
    def n(self) -> int:
        return len(self.ids)

    @property
    def provider(self) -> str:
        return str(self.meta.get("provider", "khong_ro"))

    @property
    def is_estimate(self) -> bool:
        if self.meta.get("provider") == "estimate":
            return True
        if self.sources is not None:
            return bool((self.sources == "uoc_luong").any())
        return False

    def idx(self, loc_id: str) -> int:
        """Chỉ số hàng/cột của một mã địa điểm."""
        try:
            return self._index[loc_id]
        except KeyError:
            raise KeyError(f"Mã địa điểm '{loc_id}' không có trong ma trận. Hợp lệ: {self.ids}") from None

    # ------------------------------------------------------------------ tra cứu 1 cặp
    def dist_m(self, a: str, b: str) -> int:
        return int(self._dist_m[self.idx(a), self.idx(b)])

    def dist_km(self, a: str, b: str) -> float:
        return self.dist_m(a, b) / 1000.0

    def time_s(self, a: str, b: str) -> int:
        return int(self._dur_s[self.idx(a), self.idx(b)])

    def time_min(self, a: str, b: str) -> float:
        return self.time_s(a, b) / 60.0

    # ------------------------------------------------------------------ tuyến
    def route_totals(self, route: Sequence[str]) -> RouteTotals:
        """Tổng quãng đường/thời gian di chuyển của tuyến, ví dụ ['K01','D02','D03','K01']."""
        route = [str(r) for r in route]
        if len(route) < 2:
            raise ValueError("Tuyến phải có ít nhất 2 địa điểm (điểm đi và điểm đến).")
        legs = []
        tot_m = 0
        tot_s = 0
        for a, b in zip(route[:-1], route[1:]):
            m, s = self.dist_m(a, b), self.time_s(a, b)
            tot_m += m
            tot_s += s
            legs.append(Leg(a, b, m / 1000.0, s / 60.0))
        return RouteTotals(tuple(route), tuple(legs), tot_m / 1000.0, tot_s / 60.0, tot_m, tot_s)

    # ------------------------------------------------------------------ xuất cho OR-Tools
    def _select(self, ids: Optional[Sequence[str]]) -> np.ndarray:
        if ids is None:
            return np.arange(self.n)
        return np.array([self.idx(i) for i in ids], dtype=int)

    def distance_matrix_m(self, ids: Optional[Sequence[str]] = None) -> np.ndarray:
        """Ma trận khoảng cách (mét, int64). `ids` = thứ tự node mong muốn (mặc định = self.ids)."""
        sel = self._select(ids)
        return self._dist_m[np.ix_(sel, sel)].copy()

    def time_matrix_s(self, ids: Optional[Sequence[str]] = None) -> np.ndarray:
        """Ma trận thời gian di chuyển (giây, int64). KHUYẾN NGHỊ dùng cho Time Dimension của OR-Tools."""
        sel = self._select(ids)
        return self._dur_s[np.ix_(sel, sel)].copy()

    def time_matrix_min(self, ids: Optional[Sequence[str]] = None, rounding: str = "ceil") -> np.ndarray:
        """Ma trận thời gian theo PHÚT (int64). rounding: 'ceil' (an toàn cho hạn giao) | 'round' | 'floor'.
        Lưu ý: làm tròn từng cung rồi cộng dồn sẽ lệch tổng; ưu tiên time_matrix_s nếu cần chính xác."""
        fn = {"ceil": np.ceil, "round": np.rint, "floor": np.floor}.get(rounding)
        if fn is None:
            raise ValueError("rounding phải là 'ceil', 'round' hoặc 'floor'.")
        return fn(self.time_matrix_s(ids) / 60.0).astype(np.int64)

    def submatrix(self, ids: Sequence[str]) -> "TravelMatrix":
        """Ma trận con theo danh sách mã (giữ thứ tự `ids`) - tiện cho bài test tuyến nhỏ."""
        sel = self._select(ids)
        src = None if self.sources is None else self.sources[np.ix_(sel, sel)]
        return TravelMatrix(list(ids), self._dist_m[np.ix_(sel, sel)], self._dur_s[np.ix_(sel, sel)],
                            sources=src, meta=self.meta)

    def __repr__(self) -> str:
        return f"TravelMatrix(n={self.n}, provider={self.provider!r}, ids={self.ids})"


# ---------------------------------------------------------------------- CLI nhỏ
def _main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if reconf:
            reconf(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Tính quãng đường/thời gian của một tuyến từ travel_matrix.csv")
    ap.add_argument("route", nargs="+", help="Dãy mã địa điểm, ví dụ: K01 D02 D03 K01")
    ap.add_argument("--matrix", default=str(DEFAULT_MATRIX_CSV))
    ap.add_argument("--locations", default=str(DEFAULT_LOCATIONS_CSV))
    args = ap.parse_args(argv)
    tm = TravelMatrix.from_csv(args.matrix, args.locations)
    tot = tm.route_totals(args.route)
    print(f"Nguồn dữ liệu: {tm.provider}")
    for leg in tot.legs:
        print(f"  {leg.ma_di} -> {leg.ma_den}: {leg.khoang_cach_km:7.3f} km | {leg.thoi_gian_phut:6.2f} phút")
    print(f"TỔNG: {tot.khoang_cach_km:.3f} km | {tot.thoi_gian_di_chuyen_phut:.2f} phút di chuyển "
          f"(chưa gồm thời gian dỡ hàng)")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
