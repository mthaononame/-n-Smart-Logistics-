#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_travel_matrix.py - Thành viên 4 (Bản đồ & đường đi) - dự án Smart Logistics MDVRPTW
========================================================================================

Từ `depots.csv` + `orders.csv` -> tạo bộ dữ liệu đường đi để TV2 đưa vào OR-Tools:

    output/locations.csv                 danh sách địa điểm + mã vị trí + chỉ số (loc_idx)
    output/travel_matrix.csv             ma trận khoảng cách / thời gian dạng dài (A -> B)
    output/matrix_distance_km.csv        cùng dữ liệu, dạng ma trận vuông (km)  - mở bằng Excel
    output/matrix_duration_min.csv       cùng dữ liệu, dạng ma trận vuông (phút)
    output/travel_matrix_meta.json       nguồn, thời điểm, tham số, checksum, kết quả kiểm tra
    output/GHI_CHU_NGUON_DU_LIEU.md      ghi chú nguồn/điều kiện/cách dùng (tự sinh theo lần chạy)

Ba nguồn dữ liệu (--provider):
    osrm      OSRM (OpenStreetMap) - MIỄN PHÍ, được phép lưu & dùng lâu dài (ghi nguồn). MẶC ĐỊNH.
    google    Google Maps Routes API (computeRouteMatrix) - cần API key + thanh toán; KHÔNG được lưu
              lâu dài khoảng cách/thời gian theo điều khoản -> chỉ để thử nghiệm/đối chiếu.
    estimate  Ước lượng offline: Haversine x hệ số đường vòng / tốc độ giả định. KHÔNG phải dữ liệu
              đường thực - chỉ để phát triển khi chưa có mạng.

Ví dụ:
    python build_travel_matrix.py --provider estimate
    python build_travel_matrix.py --provider osrm
    set GOOGLE_MAPS_API_KEY=xxxx            (Windows CMD;  PowerShell: $env:GOOGLE_MAPS_API_KEY="xxxx")
    python build_travel_matrix.py --provider google --small-test
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

import numpy as np
import pandas as pd

try:
    import requests
except ImportError:  # chỉ bắt buộc khi dùng provider osrm / google
    requests = None

import travel_lookup as tl

HERE = Path(__file__).resolve().parent
ENCODING = tl.ENCODING

EARTH_RADIUS_M = 6_371_008.8
VN_TZ = timezone(timedelta(hours=7))  # Việt Nam không có giờ mùa hè

# Khung toạ độ tham chiếu RỘNG quanh TP.HCM (vĩ độ min, max, kinh độ min, max) - chỉ để CẢNH BÁO nhập sai.
DEFAULT_BBOX = (10.20, 11.60, 106.20, 107.60)

DEFAULT_OSRM_URL = "https://router.project-osrm.org"
USER_AGENT = "SmartLogistics-TV4/1.0 (university course project)"  # chỉ ASCII (yêu cầu của HTTP header)
RETRY_STATUS = {429, 500, 502, 503, 504}

NGUON_ESTIMATE = "uoc_luong"
NGUON_OSRM = "osrm"
NGUON_GOOGLE = "google_routes"


# ============================================================================= lỗi
class DataError(Exception):
    """Dữ liệu đầu vào hoặc kết quả không hợp lệ."""


class ProviderError(Exception):
    """Nguồn bản đồ trả lỗi hoặc trả dữ liệu không đọc được."""


class NetworkError(ProviderError):
    """Không kết nối được tới nguồn bản đồ."""


class GuardError(Exception):
    """Chặn thao tác có nguy cơ gây nhầm lẫn/tốn tiền."""


# ============================================================================= tiện ích chung
def now_stamps() -> tuple:
    n = datetime.now(timezone.utc)
    return n.isoformat(timespec="seconds"), n.astimezone(VN_TZ).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def haversine_matrix_m(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Ma trận khoảng cách đường chim bay (mét) giữa mọi cặp điểm (WGS84, cầu bán kính trung bình)."""
    la = np.radians(np.asarray(lat, dtype=float))[:, None]
    lo = np.radians(np.asarray(lon, dtype=float))[:, None]
    dla = la - la.T
    dlo = lo - lo.T
    a = np.sin(dla / 2.0) ** 2 + np.cos(la) * np.cos(la.T) * np.sin(dlo / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * np.arcsin(np.minimum(1.0, np.sqrt(a)))


def _send_with_retry(send: Callable[[], Any], *, retries: int, backoff: float, label: str,
                     sleep: Callable[[float], None]):
    """Gọi HTTP với thử lại (lỗi mạng, 429, 5xx) theo backoff luỹ thừa."""
    last_exc = None
    net_errors = requests.exceptions.RequestException if requests is not None else ()
    for attempt in range(retries + 1):
        try:
            resp = send()
        except net_errors as exc:
            last_exc = exc
            if attempt < retries:
                sleep(backoff * (2 ** attempt))
                continue
            raise NetworkError(f"{label}: không kết nối được sau {retries + 1} lần thử "
                               f"({type(exc).__name__} - thường do mất mạng, sai DNS hoặc tường lửa).") from exc
        if resp.status_code in RETRY_STATUS and attempt < retries:
            sleep(backoff * (2 ** attempt))
            continue
        return resp
    raise NetworkError(f"{label}: thất bại ({last_exc}).")  # pragma: no cover


def _json_or_error(resp, label: str):
    try:
        return resp.json()
    except ValueError as exc:
        snippet = (getattr(resp, "text", "") or "")[:200].replace("\n", " ")
        raise ProviderError(f"{label}: phản hồi HTTP {resp.status_code} không phải JSON: {snippet!r}") from exc


# ============================================================================= BƯỚC 1-2: địa điểm
def _read_csv_utf8(path: Path, required: Sequence[str]) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise DataError(f"Không tìm thấy file: {path}")
    df = pd.read_csv(path, encoding=ENCODING, dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise DataError(f"{path.name}: thiếu cột {missing}. Các cột hiện có: {list(df.columns)}")
    for c in df.columns:
        df[c] = df[c].str.strip()
    df = df[~(df == "").all(axis=1)].reset_index(drop=True)  # bỏ dòng trống hoàn toàn
    if len(df) == 0:
        raise DataError(f"{path.name}: không có dòng dữ liệu nào.")
    return df


def load_locations(depots_csv, orders_csv, vehicles_csv=None, bbox=DEFAULT_BBOX):
    """Gộp kho + điểm giao thành 1 bảng địa điểm. Trả về (DataFrame, danh_sách_cảnh_báo).

    Thứ tự: toàn bộ kho (theo file) rồi tới các điểm giao (theo file) -> loc_idx 0..n-1.
    """
    depots = _read_csv_utf8(depots_csv, ["ma_kho", "ten_kho", "dia_chi", "vi_do", "kinh_do"])
    orders = _read_csv_utf8(orders_csv, ["ma_don", "ten_khach_hang", "dia_chi", "vi_do", "kinh_do"])
    warns: list = []

    rows = []
    for r in depots.to_dict("records"):
        rows.append({"ma_vi_tri": r["ma_kho"], "loai": "kho", "ten": r["ten_kho"],
                     "dia_chi": r["dia_chi"], "vi_do": r["vi_do"], "kinh_do": r["kinh_do"]})
    for r in orders.to_dict("records"):
        rows.append({"ma_vi_tri": r["ma_don"], "loai": "diem_giao", "ten": r["ten_khach_hang"],
                     "dia_chi": r["dia_chi"], "vi_do": r["vi_do"], "kinh_do": r["kinh_do"]})
    locs = pd.DataFrame(rows)

    # --- mã vị trí
    if (locs["ma_vi_tri"] == "").any():
        raise DataError("Có địa điểm bị bỏ trống mã (ma_kho / ma_don).")
    dup = locs.loc[locs["ma_vi_tri"].duplicated(keep=False), "ma_vi_tri"].unique().tolist()
    if dup:
        raise DataError(f"Mã vị trí bị trùng (giữa kho/đơn hoặc trong cùng file): {dup}")

    # --- toạ độ
    lat = pd.to_numeric(locs["vi_do"], errors="coerce")
    lon = pd.to_numeric(locs["kinh_do"], errors="coerce")
    bad = locs.loc[lat.isna() | lon.isna(), "ma_vi_tri"].tolist()
    if bad:
        raise DataError(f"Toạ độ không phải số (dấu thập phân phải là dấu chấm) ở: {bad}")
    if ((lat.abs() > 90) | (lon.abs() > 180)).any():
        bad = locs.loc[(lat.abs() > 90) | (lon.abs() > 180), "ma_vi_tri"].tolist()
        raise DataError(f"Toạ độ ngoài phạm vi WGS84 (nghi nhầm cột vĩ độ/kinh độ) ở: {bad}")
    locs["vi_do"] = lat.astype(float)
    locs["kinh_do"] = lon.astype(float)

    la_min, la_max, lo_min, lo_max = bbox
    outside = ~(locs["vi_do"].between(la_min, la_max) & locs["kinh_do"].between(lo_min, lo_max))
    for r in locs[outside].to_dict("records"):
        # (đảo vĩ độ <-> kinh độ ở khu vực này luôn cho |vĩ độ| > 90 nên đã bị chặn cứng ở trên)
        warns.append(f"{r['ma_vi_tri']}: toạ độ ({r['vi_do']}, {r['kinh_do']}) nằm ngoài khung tham chiếu "
                     f"TP.HCM - hãy kiểm tra lại (gõ sai chữ số?).")

    key = locs["vi_do"].round(6).astype(str) + "|" + locs["kinh_do"].round(6).astype(str)
    for _, grp in locs.groupby(key):
        if len(grp) > 1:
            warns.append(f"Các địa điểm {grp['ma_vi_tri'].tolist()} có CÙNG toạ độ -> khoảng cách giữa chúng = 0.")

    # --- đối chiếu chéo với orders/vehicles (cảnh báo mềm)
    depot_ids = set(depots["ma_kho"])
    if "kho_phuc_vu" in orders.columns:
        for r in orders.to_dict("records"):
            unknown = [k.strip() for k in r["kho_phuc_vu"].split(";") if k.strip() and k.strip() not in depot_ids]
            if unknown:
                warns.append(f"{r['ma_don']}: kho_phuc_vu chứa mã kho không tồn tại trong depots.csv: {unknown}")
    if vehicles_csv and Path(vehicles_csv).exists():
        veh = _read_csv_utf8(vehicles_csv, ["ma_xe", "ma_kho_quan_ly"])
        for r in veh.to_dict("records"):
            if r["ma_kho_quan_ly"] not in depot_ids:
                warns.append(f"{r['ma_xe']}: ma_kho_quan_ly '{r['ma_kho_quan_ly']}' không có trong depots.csv.")

    locs.insert(0, "loc_idx", np.arange(len(locs)))
    return locs, warns


def select_subset(locs: pd.DataFrame, only: Optional[str], small_test: bool) -> pd.DataFrame:
    """Lọc nhóm địa điểm nhỏ (bước 5): --small-test = 2 kho đầu + 3 điểm giao đầu; hoặc --only K01,D01,..."""
    if small_test:
        sub = pd.concat([locs[locs["loai"] == "kho"].head(2), locs[locs["loai"] == "diem_giao"].head(3)])
    elif only:
        wanted = [s.strip() for s in only.split(",") if s.strip()]
        unknown = [w for w in wanted if w not in set(locs["ma_vi_tri"])]
        if unknown:
            raise DataError(f"--only chứa mã không tồn tại: {unknown}. Hợp lệ: {locs['ma_vi_tri'].tolist()}")
        sub = locs[locs["ma_vi_tri"].isin(wanted)]
    else:
        return locs
    sub = sub.sort_values("loc_idx").copy().reset_index(drop=True)
    sub["loc_idx"] = np.arange(len(sub))
    return sub


# ============================================================================= BƯỚC 3-5: nguồn dữ liệu
@dataclass
class MatrixResult:
    dist_m: np.ndarray
    dur_s: np.ndarray
    nguon: np.ndarray  # ma trận nhãn nguồn (object), cùng kích thước
    meta: dict = field(default_factory=dict)


class EstimateProvider:
    """Ước lượng OFFLINE: Haversine x hệ số đường vòng; thời gian = quãng đường / tốc độ TB giả định."""
    name = "estimate"

    def __init__(self, circuity: float = 1.35, speed_kmh: float = 25.0):
        if circuity < 1.0:
            raise ValueError("circuity phải >= 1.0 (đường thực không thể ngắn hơn đường chim bay).")
        if speed_kmh <= 0:
            raise ValueError("speed_kmh phải > 0.")
        self.circuity = float(circuity)
        self.speed_kmh = float(speed_kmh)

    def compute(self, locs: pd.DataFrame) -> MatrixResult:
        hv = haversine_matrix_m(locs["vi_do"].to_numpy(float), locs["kinh_do"].to_numpy(float))
        dist = hv * self.circuity
        dur = dist / (self.speed_kmh / 3.6)
        nguon = np.full(dist.shape, NGUON_ESTIMATE, dtype=object)
        meta = {"method": "haversine x circuity; thoi_gian = quang_duong / toc_do",
                "circuity": self.circuity, "speed_kmh": self.speed_kmh, "n_requests": 0}
        return MatrixResult(dist, dur, nguon, meta)


class OSRMProvider:
    """OSRM Table API: GET {server}/table/v1/{profile}/{lon,lat;...}?annotations=duration,distance

    - durations: giây; distances: mét; giá trị null = không có đường đi.
    - Máy chủ mặc định giới hạn 100 toạ độ/yêu cầu (--max-table-size) -> tự chia khối nếu nhiều địa điểm hơn.
    - Thời gian là thời gian chạy tự do theo profile ô tô, KHÔNG có dữ liệu ùn tắc.
    """
    name = "osrm"

    def __init__(self, base_url: str = DEFAULT_OSRM_URL, profile: str = "driving", max_coords: int = 100,
                 pause_s: float = 1.0, timeout: float = 60.0, retries: int = 3, backoff: float = 2.0,
                 snap_warn_m: float = 200.0, user_agent: str = USER_AGENT, session=None,
                 sleep: Callable[[float], None] = time.sleep):
        if session is None and requests is None:
            raise ProviderError("Thiếu thư viện 'requests'. Cài bằng: pip install -r requirements.txt")
        if max_coords < 2:
            raise ValueError("max_coords phải >= 2.")
        self.base_url = base_url.rstrip("/")
        self.profile = profile
        self.max_coords = int(max_coords)
        self.pause_s = pause_s
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.snap_warn_m = snap_warn_m
        self.headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self.session = session if session is not None else requests.Session()
        self.sleep = sleep

    def _table(self, coords: list, rows: list, cols: list):
        """Gọi 1 yêu cầu Table cho các hàng `rows` x cột `cols` (chỉ số toàn cục). Trả (dur, dist)."""
        uniq = list(dict.fromkeys(rows + cols))
        pos = {g: k for k, g in enumerate(uniq)}
        src = [pos[g] for g in rows]
        dst = [pos[g] for g in cols]
        url = f"{self.base_url}/table/v1/{self.profile}/" + ";".join(coords[g] for g in uniq)
        params = {"annotations": "duration,distance"}
        full = list(range(len(uniq)))
        if src != full or dst != full:
            params["sources"] = ";".join(map(str, src))
            params["destinations"] = ";".join(map(str, dst))
        label = "OSRM"
        resp = _send_with_retry(
            lambda: self.session.get(url, params=params, headers=self.headers, timeout=self.timeout),
            retries=self.retries, backoff=self.backoff, label=label, sleep=self.sleep)
        data = _json_or_error(resp, label)
        code = data.get("code") if isinstance(data, dict) else None
        if resp.status_code != 200 or code != "Ok":
            msg = data.get("message", "") if isinstance(data, dict) else ""
            hint = " Gợi ý: giảm --osrm-max-coords." if code == "TooBig" else ""
            raise ProviderError(f"OSRM trả lỗi (HTTP {resp.status_code}, code={code}): {msg}.{hint}")

        def to_matrix(rows_json):
            return np.array([[np.nan if v is None else float(v) for v in r] for r in rows_json], dtype=float)

        try:
            dur = to_matrix(data["durations"])
            dist = to_matrix(data["distances"])
        except KeyError as exc:
            raise ProviderError(f"OSRM: phản hồi thiếu trường {exc}. Cần OSRM v5 hỗ trợ annotations=distance.") from exc
        shape = (len(rows), len(cols))
        if dur.shape != shape or dist.shape != shape:
            raise ProviderError(f"OSRM: kích thước bảng {dur.shape}/{dist.shape} khác kỳ vọng {shape}.")
        return dur, dist, data

    def compute(self, locs: pd.DataFrame) -> MatrixResult:
        n = len(locs)
        ids = locs["ma_vi_tri"].tolist()
        coords = [f"{lo:.6f},{la:.6f}" for lo, la in zip(locs["kinh_do"], locs["vi_do"])]  # OSRM: lon,lat
        D = np.full((n, n), np.nan)
        T = np.full((n, n), np.nan)
        snap = np.full(n, np.nan)

        if n <= self.max_coords:
            plan = [(list(range(n)), list(range(n)))]
        else:
            b = max(1, self.max_coords // 2)
            blocks = [list(range(s, min(s + b, n))) for s in range(0, n, b)]
            plan = [(bi, bj) for bi in blocks for bj in blocks]

        for k, (rows, cols) in enumerate(plan):
            if k > 0:
                self.sleep(self.pause_s)  # lịch sự với máy chủ công cộng (<= 1 yêu cầu/giây)
            dur, dist, data = self._table(coords, rows, cols)
            D[np.ix_(rows, cols)] = dist
            T[np.ix_(rows, cols)] = dur
            for g, w in zip(rows, data.get("sources", [])):
                if isinstance(w, dict) and w.get("distance") is not None:
                    snap[g] = float(w["distance"])
            for g, w in zip(cols, data.get("destinations", [])):
                if isinstance(w, dict) and w.get("distance") is not None:
                    snap[g] = float(w["distance"])

        snap_warn = [{"ma": ids[i], "cach_duong_gan_nhat_m": round(float(snap[i]), 1)}
                     for i in range(n) if np.isfinite(snap[i]) and snap[i] > self.snap_warn_m]
        nguon = np.full((n, n), NGUON_OSRM, dtype=object)
        meta = {"server": self.base_url, "profile": self.profile, "n_requests": len(plan),
                "max_coords": self.max_coords, "annotations": "duration,distance",
                "max_snap_m": None if not np.isfinite(snap).any() else round(float(np.nanmax(snap)), 1),
                "snap_warnings": snap_warn}
        return MatrixResult(D, T, nguon, meta)


class GoogleRoutesProvider:
    """Google Maps Platform - Routes API - computeRouteMatrix (REST).

    - Giới hạn: tối đa 625 phần tử (origins x destinations) / yêu cầu (không phải TRANSIT)
      -> chia khối 25 x 25.
    - Tính phí theo SỐ PHẦN TỬ (origins x destinations), không theo số yêu cầu.
    - TRAFFIC_UNAWARE (mặc định): không xét giao thông. TRAFFIC_AWARE: có giao thông, SKU đắt hơn.
    - Khoá API đọc từ biến môi trường GOOGLE_MAPS_API_KEY (không truyền qua dòng lệnh để khỏi lộ).
    """
    name = "google"
    ENDPOINT = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
    FIELD_MASK = "originIndex,destinationIndex,duration,distanceMeters,status,condition"

    def __init__(self, api_key: str, *, traffic_aware: bool = False, departure_time: Optional[datetime] = None,
                 block: int = 25, pause_s: float = 0.2, timeout: float = 60.0, retries: int = 3,
                 backoff: float = 2.0, session=None, sleep: Callable[[float], None] = time.sleep):
        if not api_key:
            raise ProviderError("Thiếu API key. Đặt biến môi trường GOOGLE_MAPS_API_KEY.")
        if session is None and requests is None:
            raise ProviderError("Thiếu thư viện 'requests'. Cài bằng: pip install -r requirements.txt")
        if block < 1 or block * block > 625:
            raise ValueError("block^2 phải <= 625 (giới hạn phần tử/yêu cầu của computeRouteMatrix).")
        if departure_time is not None and departure_time.tzinfo is None:
            raise ValueError("departure_time phải có múi giờ (ví dụ +07:00).")
        self.api_key = api_key
        self.traffic_aware = traffic_aware
        self.departure_time = departure_time
        self.block = block
        self.pause_s = pause_s
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.session = session if session is not None else requests.Session()
        self.sleep = sleep

    @staticmethod
    def parse_duration(text: str) -> float:
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s\s*", str(text))
        if not m:
            raise ProviderError(f"Google: không đọc được duration {text!r} (kỳ vọng dạng '123s').")
        return float(m.group(1))

    def _body(self, pts: list, rows: list, cols: list) -> dict:
        def wp(i):
            lat, lon = pts[i]
            return {"waypoint": {"location": {"latLng": {"latitude": lat, "longitude": lon}}}}
        body = {"origins": [wp(i) for i in rows], "destinations": [wp(j) for j in cols],
                "travelMode": "DRIVE",
                "routingPreference": "TRAFFIC_AWARE" if self.traffic_aware else "TRAFFIC_UNAWARE"}
        if self.traffic_aware and self.departure_time is not None:
            body["departureTime"] = self.departure_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return body

    @staticmethod
    def _error_text(payload) -> Optional[str]:
        """Trích lỗi dạng {"error": {...}} hoặc [{"error": {...}}]."""
        err = None
        if isinstance(payload, dict) and "error" in payload:
            err = payload["error"]
        elif isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict) and "error" in item:
                    err = item["error"]
                    break
        if err is None:
            return None
        if isinstance(err, dict):
            return f"{err.get('status', '')} {err.get('code', '')}: {err.get('message', '')}".strip()
        return str(err)

    def _call(self, pts: list, rows: list, cols: list):
        headers = {"Content-Type": "application/json", "X-Goog-Api-Key": self.api_key,
                   "X-Goog-FieldMask": self.FIELD_MASK}
        body = self._body(pts, rows, cols)
        resp = _send_with_retry(
            lambda: self.session.post(self.ENDPOINT, headers=headers, json=body, timeout=self.timeout),
            retries=self.retries, backoff=self.backoff, label="Google Routes API", sleep=self.sleep)
        payload = _json_or_error(resp, "Google Routes API")
        err = self._error_text(payload)
        if resp.status_code != 200 or err:
            raise ProviderError(f"Google Routes API lỗi (HTTP {resp.status_code}): {err or 'không rõ'}")
        if not isinstance(payload, list):
            raise ProviderError("Google Routes API: phản hồi không phải danh sách phần tử.")

        out = {}
        for e in payload:
            # JSON proto3 BỎ các trường có giá trị 0 -> originIndex/destinationIndex/distanceMeters có thể vắng mặt
            oi = int(e.get("originIndex", 0))
            di = int(e.get("destinationIndex", 0))
            status = e.get("status") or {}
            cond = e.get("condition", "ROUTE_EXISTS" if "duration" in e else "CONDITION_UNSPECIFIED")
            if int(status.get("code", 0)) != 0 or cond != "ROUTE_EXISTS" or "duration" not in e:
                out[(oi, di)] = (np.nan, np.nan)
                continue
            out[(oi, di)] = (float(e.get("distanceMeters", 0)), self.parse_duration(e["duration"]))
        return out

    def compute(self, locs: pd.DataFrame) -> MatrixResult:
        n = len(locs)
        pts = list(zip(locs["vi_do"].to_numpy(float), locs["kinh_do"].to_numpy(float)))
        D = np.full((n, n), np.nan)
        T = np.full((n, n), np.nan)
        blocks = [list(range(s, min(s + self.block, n))) for s in range(0, n, self.block)]
        n_req = 0
        n_missing = 0
        for rows in blocks:
            for cols in blocks:
                if n_req > 0:
                    self.sleep(self.pause_s)
                result = self._call(pts, rows, cols)
                n_req += 1
                for a, gi in enumerate(rows):
                    for b, gj in enumerate(cols):
                        if (a, b) in result:
                            D[gi, gj], T[gi, gj] = result[(a, b)]
                        else:
                            n_missing += 1
        nguon = np.full((n, n), NGUON_GOOGLE, dtype=object)
        meta = {"endpoint": self.ENDPOINT, "travelMode": "DRIVE",
                "routingPreference": "TRAFFIC_AWARE" if self.traffic_aware else "TRAFFIC_UNAWARE",
                "departureTime_utc": None if self.departure_time is None else
                self.departure_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "n_requests": n_req, "elements_requested": n * n, "elements_missing_in_response": n_missing}
        return MatrixResult(D, T, nguon, meta)


# ============================================================================= BƯỚC 6: hoàn thiện + kiểm tra
def finalize_matrix(res: MatrixResult, locs: pd.DataFrame, estimator: EstimateProvider, strict: bool) -> list:
    """Điền các cặp thiếu (NaN) bằng ước lượng (đánh dấu nguon='uoc_luong'), đặt đường chéo = 0."""
    n = len(locs)
    ids = locs["ma_vi_tri"].tolist()
    res.dist_m = np.array(res.dist_m, dtype=float)
    res.dur_s = np.array(res.dur_s, dtype=float)
    off = ~np.eye(n, dtype=bool)
    bad = off & (~np.isfinite(res.dist_m) | ~np.isfinite(res.dur_s))
    filled = []
    if bad.any():
        pairs = [(ids[i], ids[j]) for i, j in zip(*np.nonzero(bad))]
        if strict:
            raise ProviderError(f"Thiếu {len(pairs)} cặp không có đường đi/không trả về, ví dụ {pairs[:5]}. "
                                f"(bỏ --strict để điền bằng ước lượng và đánh dấu).")
        est = estimator.compute(locs)
        res.dist_m[bad] = est.dist_m[bad]
        res.dur_s[bad] = est.dur_s[bad]
        res.nguon[bad] = est.nguon[bad]
        filled = [[a, b] for a, b in pairs]
    np.fill_diagonal(res.dist_m, 0.0)
    np.fill_diagonal(res.dur_s, 0.0)
    return filled


def validate_matrix(ids: Sequence[str], dist_m: np.ndarray, dur_s: np.ndarray,
                    lat: np.ndarray, lon: np.ndarray) -> tuple:
    """Kiểm tra chất lượng. Lỗi nặng -> DataError. Trả (thống_kê, cảnh_báo)."""
    n = len(ids)
    if dist_m.shape != (n, n) or dur_s.shape != (n, n):
        raise DataError(f"Kích thước ma trận {dist_m.shape}/{dur_s.shape} khác {n}x{n}.")
    if not (np.isfinite(dist_m).all() and np.isfinite(dur_s).all()):
        raise DataError("Ma trận còn NaN/vô cực.")
    if (dist_m < 0).any() or (dur_s < 0).any():
        raise DataError("Ma trận có giá trị âm.")
    if np.any(np.diag(dist_m) != 0) or np.any(np.diag(dur_s) != 0):
        raise DataError("Đường chéo ma trận khác 0.")

    warns: list = []
    stats: dict = {"n": n, "n_pairs": n * (n - 1)}
    if n < 2:
        return stats, warns
    off = ~np.eye(n, dtype=bool)
    hv = haversine_matrix_m(lat, lon)

    zero = off & ((dist_m == 0) | (dur_s == 0))
    if zero.any():
        pairs = [f"{ids[i]}->{ids[j]}" for i, j in zip(*np.nonzero(zero))]
        warns.append(f"{len(pairs)} cặp có khoảng cách hoặc thời gian = 0 (hai điểm trùng/cùng điểm bám đường): "
                     f"{pairs[:6]}")

    ok = off & (dur_s > 0) & (dist_m > 0)
    speed = np.where(ok, dist_m / np.where(dur_s > 0, dur_s, 1) * 3.6, np.nan)
    slow = ok & (hv >= 300) & (speed < 5)
    fast = ok & (hv >= 300) & (speed > 90)
    if slow.any() or fast.any():
        w = [f"{ids[i]}->{ids[j]} ({speed[i, j]:.1f} km/h)" for i, j in zip(*np.nonzero(slow | fast))]
        warns.append(f"{len(w)} cặp có tốc độ ngầm định bất thường (<5 hoặc >90 km/h): {w[:6]}")

    circ = np.where(ok & (hv >= 300), dist_m / np.where(hv > 0, hv, 1), np.nan)
    bad_c = np.isfinite(circ) & ((circ < 0.99) | (circ > 3.0))
    if bad_c.any():
        w = [f"{ids[i]}->{ids[j]} (x{circ[i, j]:.2f})" for i, j in zip(*np.nonzero(bad_c))]
        warns.append(f"{len(w)} cặp có tỉ lệ đường-thực/chim-bay ngoài [0.99; 3.0] (nghi toạ độ sai/bám sai đường): {w[:6]}")

    # Bất đẳng thức tam giác theo thời gian (thông tin, không phải lỗi): t(i,k) <= t(i,j) + t(j,k)
    viol = 0
    for j in range(n):
        lhs = dur_s
        rhs = dur_s[:, [j]] + dur_s[[j], :]
        v = (lhs > rhs * 1.01 + 1.0)
        v[j, :] = False
        v[:, j] = False
        np.fill_diagonal(v, False)
        viol += int(v.sum())
    d_off = dist_m[off]
    t_off = dur_s[off]
    asym = np.abs(dist_m - dist_m.T)[off] / np.maximum(1.0, (dist_m + dist_m.T)[off] / 2.0)
    stats.update({
        "khoang_cach_km": {"min": round(float(d_off.min()) / 1000, 3), "mean": round(float(d_off.mean()) / 1000, 3),
                           "max": round(float(d_off.max()) / 1000, 3)},
        "thoi_gian_phut": {"min": round(float(t_off.min()) / 60, 2), "mean": round(float(t_off.mean()) / 60, 2),
                           "max": round(float(t_off.max()) / 60, 2)},
        "toc_do_tb_kmh": round(float(np.nansum(np.where(ok, dist_m, 0)) / max(1.0, np.nansum(np.where(ok, dur_s, 0))) * 3.6), 1),
        "he_so_duong_vong": None if not np.isfinite(circ).any() else {
            "min": round(float(np.nanmin(circ)), 3), "mean": round(float(np.nanmean(circ)), 3),
            "max": round(float(np.nanmax(circ)), 3)},
        "bat_doi_xung_max_pct": round(float(asym.max()) * 100, 1),
        "vi_pham_tam_giac_thoi_gian": viol,
    })
    return stats, warns


# ============================================================================= BƯỚC 6: ghi file
def to_long_frame(ids: Sequence[str], dist_i: np.ndarray, dur_i: np.ndarray, nguon: np.ndarray) -> pd.DataFrame:
    n = len(ids)
    ii, jj = np.nonzero(~np.eye(n, dtype=bool))  # thứ tự: theo điểm đi rồi tới điểm đến
    return pd.DataFrame({
        tl.COL_FROM: [ids[i] for i in ii],
        tl.COL_TO: [ids[j] for j in jj],
        tl.COL_DIST_M: dist_i[ii, jj],
        tl.COL_TIME_S: dur_i[ii, jj],
        tl.COL_DIST_KM: np.round(dist_i[ii, jj] / 1000.0, 3),
        tl.COL_TIME_MIN: np.round(dur_i[ii, jj] / 60.0, 2),
        tl.COL_SOURCE: nguon[ii, jj],
    })[tl.MATRIX_COLUMNS]


def write_outputs(out_dir: Path, locs: pd.DataFrame, dist_i: np.ndarray, dur_i: np.ndarray, nguon: np.ndarray) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    ids = locs["ma_vi_tri"].tolist()
    paths = {
        "locations.csv": out_dir / "locations.csv",
        "travel_matrix.csv": out_dir / "travel_matrix.csv",
        "matrix_distance_km.csv": out_dir / "matrix_distance_km.csv",
        "matrix_duration_min.csv": out_dir / "matrix_duration_min.csv",
    }
    locs[tl.LOCATION_COLUMNS].to_csv(paths["locations.csv"], index=False, encoding=ENCODING)
    to_long_frame(ids, dist_i, dur_i, nguon).to_csv(paths["travel_matrix.csv"], index=False, encoding=ENCODING)
    pd.DataFrame(np.round(dist_i / 1000.0, 3), index=ids, columns=ids).to_csv(
        paths["matrix_distance_km.csv"], index_label="ma_di", encoding=ENCODING, float_format="%.3f")
    pd.DataFrame(np.round(dur_i / 60.0, 2), index=ids, columns=ids).to_csv(
        paths["matrix_duration_min.csv"], index_label="ma_di", encoding=ENCODING, float_format="%.2f")
    return {name: sha256_file(p) for name, p in paths.items()}


def render_notes(meta: dict) -> str:
    """Sinh GHI_CHU_NGUON_DU_LIEU.md phản ánh đúng lần chạy này."""
    prov = meta["provider"]
    d = meta["provider_detail"]
    val = meta["validation"]
    n, pairs = meta["n_locations"], meta["n_pairs"]
    L = []
    add = L.append
    add("# Ghi chú nguồn dữ liệu - ma trận đường đi (Thành viên 4)\n")
    add(f"_Tự sinh bởi `build_travel_matrix.py` lúc **{meta['created_vn']}** (giờ Việt Nam). "
        f"Không sửa tay - hãy chạy lại script để cập nhật._\n")

    if prov == "estimate":
        add("> ⚠️ **ĐÂY LÀ DỮ LIỆU ƯỚC LƯỢNG, KHÔNG PHẢI DỮ LIỆU THEO MẠNG ĐƯỜNG.**")
        add(f"> Khoảng cách = đường chim bay (Haversine) × hệ số đường vòng **{d.get('circuity')}**; "
            f"thời gian = khoảng cách ÷ tốc độ trung bình giả định **{d.get('speed_kmh')} km/h**.")
        add("> Hai tham số này là **giả định, chưa được hiệu chỉnh** bằng dữ liệu thực. Chỉ dùng để lập trình/kiểm thử "
            "luồng dữ liệu. Trước khi đánh giá chính thức hãy chạy `python build_travel_matrix.py --provider osrm`.\n")
        if meta.get("fallback_from"):
            add(f"> Lưu ý: lần chạy này định lấy dữ liệu từ **{meta['fallback_from']}** nhưng bị lỗi mạng nên đã "
                f"chuyển sang ước lượng (`--fallback-estimate`).\n")
    elif prov == "google":
        add("> ⚠️ **ĐIỀU KHOẢN LƯU TRỮ:** theo *Google Maps Platform Service Specific Terms* (bản sửa đổi 04/06/2026, "
            "mục Routes API) chỉ được cache tạm **toạ độ (lat/lng) tối đa 30 ngày**; điều khoản chung cấm lưu/cache "
            "nội dung Google ngoài các ngoại lệ được liệt kê, và mục Routes API **không liệt kê ngoại lệ cho "
            "khoảng cách/thời gian**. Ngoài ra không được dùng nội dung Routes API cùng với bản đồ không phải của Google.")
        add("> ➜ Thư mục này chỉ để **thử nghiệm / đối chiếu ngắn hạn**. Không đưa lên Git/Google Sheet dùng lâu dài; "
            "dữ liệu lưu trữ chính thức của dự án nên lấy từ OSRM/OpenStreetMap. Hãy đọc bản điều khoản hiện hành "
            "và xin ý kiến giảng viên khi cần.\n")

    add("## 1. Tóm tắt lần lấy dữ liệu\n")
    add("| Mục | Giá trị |\n|---|---|")
    labels = {"osrm": "OSRM (OpenStreetMap) - Table API", "google": "Google Maps Platform - Routes API computeRouteMatrix",
              "estimate": "Ước lượng offline (Haversine × hệ số đường vòng)"}
    add(f"| Nguồn | {labels.get(prov, prov)} |")
    add(f"| Thời điểm lấy | {meta['created_vn']} (UTC: {meta['created_utc']}) |")
    add(f"| Số địa điểm | {n} ({meta['n_kho']} kho + {meta['n_diem_giao']} điểm giao) |")
    add(f"| Số cặp có hướng (A≠B) | {pairs} |")
    add("| Phương tiện | Ô tô (OSRM profile `driving` / Google `DRIVE`) - **không** xét quy định cấm tải, giờ cấm, "
        "tải trọng xe |")
    if prov == "osrm":
        add(f"| Máy chủ | `{d.get('server')}` (profile `{d.get('profile')}`, {d.get('n_requests')} yêu cầu) |")
        add("| Giao thông | **Không xét** - thời gian chạy tự do theo hạn tốc độ/loại đường của profile |")
        add(f"| Độ lệch bám đường lớn nhất của toạ độ | {d.get('max_snap_m')} m |")
    elif prov == "google":
        add(f"| Chế độ | `{d.get('routingPreference')}`"
            f"{'' if not d.get('departureTime_utc') else ', departureTime=' + d['departureTime_utc']} |")
        add(f"| Số phần tử tính phí | {d.get('elements_requested')} (= số origin × số destination), "
            f"{d.get('n_requests')} yêu cầu |")
    elif prov == "estimate":
        add(f"| Tham số giả định | hệ số đường vòng = {d.get('circuity')}, tốc độ = {d.get('speed_kmh')} km/h |")
        add("| Giao thông | Không xét |")
    if meta.get("filled_pairs"):
        add(f"| Cặp phải điền bằng ước lượng | {len(meta['filled_pairs'])} (đánh dấu `uoc_luong` ở cột `nguon`) |")
    add("")

    add("## 2. Điều kiện sử dụng / bản quyền\n")
    if prov == "osrm":
        add("- Dữ liệu bản đồ: **© OpenStreetMap contributors**, giấy phép **ODbL**. Cho phép lưu và dùng lâu dài nếu "
            "**ghi nguồn**; nếu công bố công khai một cơ sở dữ liệu phái sinh thì có thêm yêu cầu chia sẻ tương tự - "
            "hãy đọc https://www.openstreetmap.org/copyright.")
        add("- Định tuyến: Project OSRM (mã nguồn mở). Máy chủ công cộng `router.project-osrm.org` là máy chủ **demo**, "
            "chỉ nên dùng thử/nhẹ (lần chạy này chỉ cần rất ít yêu cầu). Nếu cần dùng thường xuyên hoặc nhiều điểm, "
            "tự dựng OSRM bằng Docker và truyền `--osrm-url http://localhost:5000`.")
        add("- Khi trình bày báo cáo/ứng dụng, ghi: *\"Dữ liệu đường: © OpenStreetMap contributors; định tuyến: OSRM\"*.")
    elif prov == "google":
        add("- Xem cảnh báo ở đầu file. Thanh toán: tính theo phần tử; hạn mức miễn phí hằng tháng phụ thuộc SKU "
            "(Essentials cho TRAFFIC_UNAWARE; Pro cho TRAFFIC_AWARE) - kiểm tra bảng giá hiện hành của Google.")
    else:
        add("- Không dùng dữ liệu bên thứ ba (chỉ dùng toạ độ của dự án) nên không có ràng buộc bản quyền, "
            "nhưng cũng **không có giá trị như dữ liệu đường thực**.")
    add("")

    add("## 3. Giới hạn cần nhớ khi diễn giải\n")
    add("- Thời gian là **ước tính di chuyển**, không phải thời gian xe chạy thực tế (không có ùn tắc theo giờ, "
        "đèn đỏ, cấm tải, đỗ xe, tìm cổng giao hàng).")
    add("- Thời gian **chưa gồm** thời gian dỡ hàng (`thoi_gian_phuc_vu_phut` trong `orders.csv`) - TV2 cộng riêng.")
    add("- Ma trận **bất đối xứng**; đường chéo = 0 và không có trong `travel_matrix.csv`.")
    add("- Kết quả đã làm tròn về số nguyên: mét và giây.\n")

    add("## 4. Kiểm tra chất lượng tự động\n")
    if val.get("khoang_cach_km"):
        add(f"- Khoảng cách: min {val['khoang_cach_km']['min']} / TB {val['khoang_cach_km']['mean']} / "
            f"max {val['khoang_cach_km']['max']} km")
        add(f"- Thời gian: min {val['thoi_gian_phut']['min']} / TB {val['thoi_gian_phut']['mean']} / "
            f"max {val['thoi_gian_phut']['max']} phút; tốc độ trung bình ngầm định ≈ {val['toc_do_tb_kmh']} km/h")
        if val.get("he_so_duong_vong"):
            h = val["he_so_duong_vong"]
            add(f"- Hệ số đường-thực/chim-bay: min {h['min']} / TB {h['mean']} / max {h['max']}")
        add(f"- Bất đối xứng lớn nhất giữa A→B và B→A: {val['bat_doi_xung_max_pct']}%")
        add(f"- Số bộ ba vi phạm bất đẳng thức tam giác về thời gian (thông tin): {val['vi_pham_tam_giac_thoi_gian']}")
    if meta["warnings"]:
        add("- Cảnh báo:")
        for w in meta["warnings"]:
            add(f"  - {w}")
    else:
        add("- Không có cảnh báo.")
    add("")

    add("## 5. Cách sử dụng (TV2)\n")
    add("```python")
    add("from travel_lookup import TravelMatrix")
    add("tm = TravelMatrix.from_csv()                    # đọc output/travel_matrix.csv + locations.csv")
    add("tm.dist_km('K01', 'D02'); tm.time_min('K01', 'D02')")
    add("tot = tm.route_totals(['K01', 'D02', 'D03', 'K01'])   # tổng km + phút di chuyển của 1 tuyến")
    add("dist = tm.distance_matrix_m().tolist()          # mét (int)  -> OR-Tools arc cost")
    add("time = tm.time_matrix_s().tolist()              # giây (int) -> OR-Tools Time Dimension")
    add("# chỉ số node = vị trí trong tm.ids (kho trước, điểm giao sau)")
    add("```\n")
    add("Cột của `travel_matrix.csv`: `ma_di, ma_den, khoang_cach_m, thoi_gian_s, khoang_cach_km, "
        "thoi_gian_phut, nguon`.\n")
    add("## 6. Tính tái lập\n")
    add("| File đầu vào | SHA-256 |\n|---|---|")
    for name, info in meta["inputs"].items():
        add(f"| {name} | `{info['sha256'][:16]}…` |")
    add("")
    return "\n".join(L) + "\n"


# ============================================================================= điều phối
def guard_overwrite(out_dir: Path, new_provider: str, force: bool) -> None:
    """Không để bản ƯỚC LƯỢNG đè lên bản dữ liệu đường thực đã có."""
    meta_path = out_dir / "travel_matrix_meta.json"
    if force or new_provider != "estimate" or not meta_path.exists():
        return
    try:
        old = json.loads(meta_path.read_text(encoding="utf-8")).get("provider")
    except (ValueError, OSError):
        return
    if old in ("osrm", "google"):
        raise GuardError(f"{out_dir} đang chứa dữ liệu ĐƯỜNG THỰC (nguồn: {old}). Chạy ước lượng sẽ ghi đè. "
                         f"Dùng --out <thư mục khác> hoặc thêm --force nếu bạn chắc chắn.")


def parse_departure(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataError(f"--departure-time không đúng định dạng ISO 8601 (vd 2026-10-26T08:00:00+07:00): {text}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=VN_TZ)
    if dt < datetime.now(timezone.utc):
        raise DataError("--departure-time phải ở tương lai (Google từ chối thời điểm đã qua).")
    return dt


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="build_travel_matrix.py",
        description="TV4: tạo ma trận khoảng cách/thời gian theo mạng đường cho bài toán MDVRPTW.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Ví dụ:" + __doc__.split("Ví dụ:")[-1])
    p.add_argument("--provider", choices=["osrm", "google", "estimate"], default="osrm")
    p.add_argument("--depots", default=str(HERE / "data" / "depots.csv"))
    p.add_argument("--orders", default=str(HERE / "data" / "orders.csv"))
    p.add_argument("--vehicles", default=str(HERE / "data" / "vehicles.csv"),
                   help="(tuỳ chọn) chỉ để đối chiếu mã kho của xe")
    p.add_argument("--out", default=None, help="Thư mục đầu ra (mặc định: output/, riêng google: output_google/)")
    sub = p.add_mutually_exclusive_group()
    sub.add_argument("--only", help="Chỉ lấy các mã này, ví dụ K01,K02,D01,D02,D03")
    sub.add_argument("--small-test", action="store_true", help="Nhóm nhỏ: 2 kho đầu + 3 điểm giao đầu (bước 5)")
    p.add_argument("--strict", action="store_true", help="Lỗi nếu thiếu cặp thay vì điền bằng ước lượng")
    p.add_argument("--fallback-estimate", action="store_true",
                   help="Nếu OSRM lỗi mạng -> chuyển sang ước lượng (có đánh dấu rõ)")
    p.add_argument("--force", action="store_true", help="Cho phép ước lượng ghi đè dữ liệu đường thực")
    p.add_argument("--quiet", action="store_true")
    g = p.add_argument_group("OSRM")
    g.add_argument("--osrm-url", default=DEFAULT_OSRM_URL)
    g.add_argument("--osrm-profile", default="driving")
    g.add_argument("--osrm-max-coords", type=int, default=100, help="Số toạ độ tối đa/yêu cầu của máy chủ (mặc định 100)")
    g.add_argument("--osrm-pause", type=float, default=1.0, help="Giây nghỉ giữa các yêu cầu (mặc định 1.0)")
    g.add_argument("--timeout", type=float, default=60.0, help="Timeout mỗi yêu cầu HTTP (giây)")
    g.add_argument("--retries", type=int, default=3, help="Số lần thử lại khi lỗi mạng/429/5xx (mặc định 3)")
    g.add_argument("--backoff", type=float, default=2.0, help="Giây chờ cơ sở giữa các lần thử lại (nhân đôi mỗi lần)")
    g.add_argument("--user-agent", default=USER_AGENT)
    g = p.add_argument_group("Google Routes API (khoá đọc từ biến môi trường GOOGLE_MAPS_API_KEY)")
    g.add_argument("--traffic-aware", action="store_true", help="Có giao thông (SKU Pro, đắt hơn)")
    g.add_argument("--departure-time", help="ISO 8601 ở tương lai, chỉ dùng với --traffic-aware")
    g.add_argument("--max-elements", type=int, default=1000, help="Chặn nếu số phần tử (n×n) vượt ngưỡng này")
    g = p.add_argument_group("Ước lượng offline")
    g.add_argument("--circuity", type=float, default=1.35, help="Hệ số đường vòng (mặc định 1.35 - GIẢ ĐỊNH)")
    g.add_argument("--speed-kmh", type=float, default=25.0, help="Tốc độ TB giả định km/h (mặc định 25 - GIẢ ĐỊNH)")
    return p


def run(args: argparse.Namespace, session=None) -> dict:
    """Thực hiện toàn bộ quy trình. `session` chỉ dùng để kiểm thử (HTTP giả)."""
    log: Callable[..., None] = (lambda *a, **k: None) if args.quiet else print
    t0 = time.time()

    # ---- Bước 1-2: nạp địa điểm, liệt kê cặp
    locs_all, warns = load_locations(args.depots, args.orders, args.vehicles)
    locs = select_subset(locs_all, args.only, args.small_test)
    n = len(locs)
    if n < 2:
        raise DataError("Cần ít nhất 2 địa điểm.")
    ids = locs["ma_vi_tri"].tolist()
    n_kho = int((locs["loai"] == "kho").sum())
    log(f"[1/6] Nạp dữ liệu: {n} địa điểm ({n_kho} kho + {n - n_kho} điểm giao) -> {n * (n - 1)} cặp có hướng (A≠B)")
    for w in warns:
        log(f"      ! {w}")

    estimator = EstimateProvider(args.circuity, args.speed_kmh)
    fallback_from = None

    # ---- Bước 3-5: chọn nguồn
    if args.provider == "estimate":
        provider = estimator
    elif args.provider == "osrm":
        provider = OSRMProvider(args.osrm_url, args.osrm_profile, args.osrm_max_coords, args.osrm_pause,
                                args.timeout, retries=args.retries, backoff=args.backoff,
                                user_agent=args.user_agent, session=session)
    else:
        key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
        if not key:
            raise ProviderError("Chưa có GOOGLE_MAPS_API_KEY. Windows CMD: set GOOGLE_MAPS_API_KEY=xxxx | "
                                "PowerShell: $env:GOOGLE_MAPS_API_KEY=\"xxxx\". (Hoặc dùng --provider osrm, miễn phí.)")
        if n * n > args.max_elements:
            raise GuardError(f"Sẽ tốn {n * n} phần tử tính phí (> --max-elements {args.max_elements}). "
                             f"Thử trước với --small-test, hoặc tăng --max-elements khi chắc chắn.")
        dep = parse_departure(args.departure_time) if args.traffic_aware else None
        if args.departure_time and not args.traffic_aware:
            warns.append("--departure-time bị bỏ qua vì không có --traffic-aware.")
        provider = GoogleRoutesProvider(key, traffic_aware=args.traffic_aware, departure_time=dep,
                                        timeout=args.timeout, retries=args.retries, backoff=args.backoff,
                                        session=session)
        log(f"      Google: {n * n} phần tử tính phí (kiểm tra bảng giá/hạn mức hiện hành trước khi chạy lớn).")

    out_dir = Path(args.out) if args.out else HERE / ("output_google" if args.provider == "google" else "output")
    guard_overwrite(out_dir, args.provider, args.force)

    log(f"[2/6] Lấy ma trận từ nguồn '{args.provider}' ...")
    try:
        res = provider.compute(locs)
    except NetworkError as exc:
        if args.provider == "osrm" and args.fallback_estimate:
            log(f"      ! {exc}\n      ! CHUYỂN SANG ƯỚC LƯỢNG (--fallback-estimate). Dữ liệu KHÔNG phải đường thực!")
            fallback_from = "osrm"
            provider = estimator
            res = estimator.compute(locs)
        else:
            raise ProviderError(f"{exc} Kiểm tra mạng, hoặc dùng --fallback-estimate / --provider estimate.") from exc
    final_provider = "estimate" if fallback_from else args.provider
    warns.extend(f"Toạ độ {s['ma']} cách đường gần nhất {s['cach_duong_gan_nhat_m']} m (có thể nằm trong khuôn viên/ngõ cụt)."
                 for s in res.meta.get("snap_warnings", []))

    log("[3/6] Hoàn thiện & kiểm tra chất lượng ...")
    filled = finalize_matrix(res, locs, estimator, args.strict)
    if filled:
        warns.append(f"{len(filled)} cặp không có dữ liệu từ nguồn -> điền bằng ước lượng: {filled[:6]}")
    dist_i = np.rint(res.dist_m).astype(np.int64)
    dur_i = np.rint(res.dur_s).astype(np.int64)
    stats, vwarns = validate_matrix(ids, dist_i.astype(float), dur_i.astype(float),
                                    locs["vi_do"].to_numpy(float), locs["kinh_do"].to_numpy(float))
    warns.extend(vwarns)

    # ---- Bước 6: ghi file
    log(f"[4/6] Ghi file vào {out_dir} ...")
    hashes = write_outputs(out_dir, locs, dist_i, dur_i, res.nguon)

    created_utc, created_vn = now_stamps()
    meta = {
        "schema_version": 1,
        "provider": final_provider,
        "fallback_from": fallback_from,
        "provider_detail": res.meta,
        "created_utc": created_utc,
        "created_vn": created_vn,
        "n_locations": n, "n_kho": n_kho, "n_diem_giao": n - n_kho, "n_pairs": n * (n - 1),
        "location_ids": ids,
        "units": {tl.COL_DIST_M: "mét (int)", tl.COL_TIME_S: "giây (int)"},
        "inputs": {Path(p).name: {"path": str(p), "sha256": sha256_file(Path(p))}
                   for p in (args.depots, args.orders)},
        "outputs_sha256": hashes,
        "validation": stats,
        "warnings": warns,
        "filled_pairs": filled,
        "runtime_s": round(time.time() - t0, 2),
        "software": {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
                     "requests": getattr(requests, "__version__", None)},
    }
    (out_dir / "travel_matrix_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log("[5/6] Sinh ghi chú nguồn dữ liệu ...")
    (out_dir / "GHI_CHU_NGUON_DU_LIEU.md").write_text(render_notes(meta), encoding="utf-8")

    log(f"[6/6] Xong trong {meta['runtime_s']} giây. Nguồn dữ liệu: {final_provider.upper()}")
    if stats.get("khoang_cach_km"):
        log(f"      Khoảng cách {stats['khoang_cach_km']['min']}-{stats['khoang_cach_km']['max']} km "
            f"(TB {stats['khoang_cach_km']['mean']}); thời gian {stats['thoi_gian_phut']['min']}-"
            f"{stats['thoi_gian_phut']['max']} phút; tốc độ TB ≈ {stats['toc_do_tb_kmh']} km/h")
    for w in warns:
        log(f"      ! {w}")
    if final_provider == "estimate":
        log("      >>> CHÚ Ý: đây là dữ liệu ƯỚC LƯỢNG. Dùng --provider osrm để lấy dữ liệu theo mạng đường.")
    if final_provider == "google":
        log("      >>> CHÚ Ý: không lưu/chia sẻ lâu dài kết quả Google (xem GHI_CHU_NGUON_DU_LIEU.md).")
    return meta


def main(argv: Optional[Sequence[str]] = None, session=None) -> int:
    for stream in (sys.stdout, sys.stderr):  # tránh lỗi Unicode trên console Windows (cp1252)
        reconf = getattr(stream, "reconfigure", None)
        if reconf:
            try:
                reconf(encoding="utf-8", errors="replace")
            except Exception:
                pass
    args = build_parser().parse_args(argv)
    try:
        run(args, session=session)
    except (DataError, GuardError) as exc:
        print(f"LỖI: {exc}", file=sys.stderr)
        return 2
    except ProviderError as exc:
        print(f"LỖI NGUỒN DỮ LIỆU: {exc}", file=sys.stderr)
        return 3
    except ValueError as exc:  # tham số không hợp lệ (vd --circuity < 1)
        print(f"LỖI THAM SỐ: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Đã dừng.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
