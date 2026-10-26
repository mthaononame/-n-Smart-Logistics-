# -*- coding: utf-8 -*-
"""
Kiểm thử cho TV4. Chạy:   python -m unittest discover -s tests -v      (không cần cài pytest)

Không gọi mạng thật: OSRM và Google được thay bằng "session giả" mô phỏng đúng định dạng phản hồi
của từng API (kể cả việc JSON proto3 của Google BỎ các trường bằng 0 và trả phần tử không theo thứ tự).
"""
import io
import json
import os
import random
import sys
import tempfile
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import build_travel_matrix as btm  # noqa: E402
import demo_small_route as demo  # noqa: E402
import travel_lookup as tl  # noqa: E402

DEPOTS = ROOT / "data" / "depots.csv"
ORDERS = ROOT / "data" / "orders.csv"
VEHICLES = ROOT / "data" / "vehicles.csv"


# --------------------------------------------------------------------------- hàng "thật" dùng để đối chiếu
def truth(lon1, lat1, lon2, lat2):
    """Quãng đường (m) và thời gian (s) 'thật' của server giả: bất đối xứng nhẹ, ~30 km/h."""
    hv = btm.haversine_matrix_m(np.array([lat1, lat2]), np.array([lon1, lon2]))[0, 1]
    dist = hv * 1.3 * (1.03 if (lon1, lat1) < (lon2, lat2) else 1.0)
    return dist, dist / (30 / 3.6)


def expected_matrix(locs, decimals=6):
    """decimals=6: OSRM nhận toạ độ làm tròn 6 chữ số; decimals=None: Google nhận toạ độ đầy đủ."""
    rnd = (lambda x: x) if decimals is None else (lambda x: round(x, decimals))
    pts = [(rnd(lo), rnd(la)) for lo, la in zip(locs["kinh_do"], locs["vi_do"])]
    n = len(pts)
    D = np.zeros((n, n))
    T = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i != j:
                D[i, j], T[i, j] = truth(*pts[i], *pts[j])
    return D, T


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeOSRMSession:
    """Mô phỏng GET /table/v1/{profile}/{lon,lat;...}?annotations=...&sources=..&destinations=.."""

    def __init__(self, fail_first=0, null_pairs=(), snap_override=None, code="Ok", raise_exc=None):
        self.calls = []
        self.fail_first = fail_first
        self.null_pairs = set(null_pairs)
        self.snap_override = snap_override or {}
        self.code = code
        self.raise_exc = raise_exc

    def get(self, url, params=None, headers=None, timeout=None):
        params = dict(params or {})
        self.calls.append((url, params, headers))
        if self.raise_exc:
            raise self.raise_exc
        if self.fail_first > 0:
            self.fail_first -= 1
            return FakeResponse({"code": "Error"}, 503)
        if self.code != "Ok":
            return FakeResponse({"code": self.code, "message": "giả lập lỗi"}, 400 if self.code == "TooBig" else 200)
        coords = url.split("/table/v1/")[1].split("/", 1)[1]
        pts = [tuple(float(x) for x in c.split(",")) for c in coords.split(";")]
        src = [int(x) for x in params["sources"].split(";")] if "sources" in params else list(range(len(pts)))
        dst = [int(x) for x in params["destinations"].split(";")] if "destinations" in params else list(range(len(pts)))
        assert params["annotations"] == "duration,distance"
        durs, dists = [], []
        for a in src:
            rd, rt = [], []
            for b in dst:
                if a == b:
                    rd.append(0.0)
                    rt.append(0.0)
                elif (pts[a], pts[b]) in self.null_pairs:
                    rd.append(None)
                    rt.append(None)
                else:
                    d, t = truth(*pts[a], *pts[b])
                    rd.append(d)
                    rt.append(t)
            dists.append(rd)
            durs.append(rt)
        wp = lambda p: {"hint": "x", "distance": self.snap_override.get(p, 8.0), "name": "", "location": list(p)}
        return FakeResponse({"code": "Ok", "durations": durs, "distances": dists,
                             "sources": [wp(pts[a]) for a in src], "destinations": [wp(pts[b]) for b in dst]})


class FakeGoogleSession:
    """Mô phỏng POST computeRouteMatrix: phần tử xáo trộn, bỏ trường bằng 0 (proto3), có thể thiếu tuyến."""

    def __init__(self, missing=(), http_status=200, error_payload=None, fail_first=0):
        self.calls = []
        self.missing = set(missing)
        self.http_status = http_status
        self.error_payload = error_payload
        self.fail_first = fail_first

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append((url, headers, json))
        if self.fail_first > 0:
            self.fail_first -= 1
            return FakeResponse({"error": {"code": 503}}, 503)
        if self.error_payload is not None:
            return FakeResponse(self.error_payload, self.http_status)
        org, des = json["origins"], json["destinations"]
        assert len(org) * len(des) <= 625
        ll = lambda w: (w["waypoint"]["location"]["latLng"]["longitude"], w["waypoint"]["location"]["latLng"]["latitude"])
        out = []
        for a, o in enumerate(org):
            for b, d in enumerate(des):
                e = {}
                if a:
                    e["originIndex"] = a
                if b:
                    e["destinationIndex"] = b
                po, pd_ = ll(o), ll(d)
                if (po, pd_) in self.missing:
                    e["status"] = {}
                    e["condition"] = "ROUTE_NOT_FOUND"
                else:
                    dist, dur = truth(*po, *pd_)
                    if round(dist):
                        e["distanceMeters"] = int(round(dist))
                    e["duration"] = f"{int(round(dur))}s"
                    e["status"] = {}
                    e["condition"] = "ROUTE_EXISTS"
                out.append(e)
        random.Random(1).shuffle(out)
        return FakeResponse(out, self.http_status)


def real_locations():
    locs, _ = btm.load_locations(DEPOTS, ORDERS, VEHICLES)
    return locs


def write_csv(path, text):
    Path(path).write_text(text, encoding="utf-8-sig")


def run_cli(argv, session=None):
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out), redirect_stderr(buf_err):
        code = btm.main(argv, session=session)
    return code, buf_out.getvalue(), buf_err.getvalue()


# =========================================================================== 1. Haversine
class TestHaversine(unittest.TestCase):
    def test_properties(self):
        lat = np.array([10.8, 10.82, 10.77])
        lon = np.array([106.69, 106.75, 106.70])
        H = btm.haversine_matrix_m(lat, lon)
        self.assertTrue(np.all(np.diag(H) == 0))
        np.testing.assert_allclose(H, H.T)
        self.assertTrue((H[~np.eye(3, dtype=bool)] > 0).all())

    def test_one_degree_latitude(self):
        H = btm.haversine_matrix_m(np.array([10.0, 11.0]), np.array([106.0, 106.0]))
        self.assertAlmostEqual(H[0, 1] / 1000, 111.195, delta=0.15)  # 6371.0088 km * pi/180


# =========================================================================== 2. Nạp địa điểm
class TestLoadLocations(unittest.TestCase):
    def test_real_data(self):
        locs, warns = btm.load_locations(DEPOTS, ORDERS, VEHICLES)
        self.assertEqual(len(locs), 12)
        self.assertEqual(locs["ma_vi_tri"].tolist(), ["K01", "K02"] + [f"D{i:02d}" for i in range(1, 11)])
        self.assertEqual(locs["loai"].tolist(), ["kho"] * 2 + ["diem_giao"] * 10)
        self.assertEqual(locs["loc_idx"].tolist(), list(range(12)))
        self.assertEqual(warns, [], msg=f"Dữ liệu thật không nên có cảnh báo: {warns}")
        self.assertAlmostEqual(locs.loc[0, "vi_do"], 10.80013297922369)

    def _tmp_files(self, depots, orders):
        d = tempfile.mkdtemp()
        write_csv(Path(d) / "d.csv", depots)
        write_csv(Path(d) / "o.csv", orders)
        return Path(d) / "d.csv", Path(d) / "o.csv"

    HDR_D = "ma_kho,ten_kho,dia_chi,vi_do,kinh_do\n"
    HDR_O = "ma_don,ten_khach_hang,dia_chi,vi_do,kinh_do,kho_phuc_vu\n"

    def test_duplicate_id_between_depot_and_order(self):
        d, o = self._tmp_files(self.HDR_D + "K01,A,x,10.8,106.7\n", self.HDR_O + "K01,B,x,10.7,106.6,K01\n")
        with self.assertRaises(btm.DataError):
            btm.load_locations(d, o)

    def test_missing_column(self):
        d, o = self._tmp_files("ma_kho,ten_kho\nK01,A\n", self.HDR_O + "D01,B,x,10.7,106.6,K01\n")
        with self.assertRaises(btm.DataError):
            btm.load_locations(d, o)

    def test_non_numeric_and_comma_decimal(self):
        d, o = self._tmp_files(self.HDR_D + "K01,A,x,10.8,106.7\n", self.HDR_O + 'D01,B,x,"10,7",106.6,K01\n')
        with self.assertRaises(btm.DataError):
            btm.load_locations(d, o)

    def test_swapped_lat_lon_is_rejected(self):
        d, o = self._tmp_files(self.HDR_D + "K01,A,x,10.8,106.7\n", self.HDR_O + "D01,B,x,106.6,10.7,K01\n")
        with self.assertRaises(btm.DataError) as cm:
            btm.load_locations(d, o)
        self.assertIn("nhầm", str(cm.exception))
        self.assertIn("D01", str(cm.exception))

    def test_typo_outside_hcmc_is_warned(self):
        d, o = self._tmp_files(self.HDR_D + "K01,A,x,10.8,106.7\n", self.HDR_O + "D01,B,x,10.7,160.6,K01\n")
        _, warns = btm.load_locations(d, o)
        self.assertTrue(any("D01" in w and "ngoài khung" in w for w in warns), warns)

    def test_lat_out_of_range(self):
        d, o = self._tmp_files(self.HDR_D + "K01,A,x,10.8,106.7\n", self.HDR_O + "D01,B,x,200,10.7,K01\n")
        with self.assertRaises(btm.DataError):
            btm.load_locations(d, o)

    def test_same_coordinates_and_unknown_depot_reference(self):
        d, o = self._tmp_files(self.HDR_D + "K01,A,x,10.8,106.7\n",
                               self.HDR_O + "D01,B,x,10.8,106.7,K01;K09\n")
        _, warns = btm.load_locations(d, o)
        self.assertTrue(any("CÙNG toạ độ" in w for w in warns))
        self.assertTrue(any("K09" in w for w in warns))

    def test_subset(self):
        locs = real_locations()
        sub = btm.select_subset(locs, None, True)
        self.assertEqual(sub["ma_vi_tri"].tolist(), ["K01", "K02", "D01", "D02", "D03"])
        self.assertEqual(sub["loc_idx"].tolist(), [0, 1, 2, 3, 4])
        sub2 = btm.select_subset(locs, "D05, K02", False)
        self.assertEqual(sub2["ma_vi_tri"].tolist(), ["K02", "D05"])
        with self.assertRaises(btm.DataError):
            btm.select_subset(locs, "K01,ZZZ", False)


# =========================================================================== 3. Provider ước lượng
class TestEstimate(unittest.TestCase):
    def test_estimate(self):
        locs = real_locations()
        r = btm.EstimateProvider(1.4, 30).compute(locs)
        H = btm.haversine_matrix_m(locs["vi_do"].to_numpy(float), locs["kinh_do"].to_numpy(float))
        np.testing.assert_allclose(r.dist_m, H * 1.4)
        np.testing.assert_allclose(r.dur_s, H * 1.4 / (30 / 3.6))
        self.assertTrue((r.nguon == btm.NGUON_ESTIMATE).all())

    def test_invalid_params(self):
        with self.assertRaises(ValueError):
            btm.EstimateProvider(0.9, 25)
        with self.assertRaises(ValueError):
            btm.EstimateProvider(1.3, 0)


# =========================================================================== 4. OSRM
class TestOSRM(unittest.TestCase):
    def setUp(self):
        self.locs = real_locations()
        self.D, self.T = expected_matrix(self.locs)

    def test_single_request(self):
        s = FakeOSRMSession()
        r = btm.OSRMProvider(session=s, sleep=lambda x: None).compute(self.locs)
        self.assertEqual(len(s.calls), 1)
        url, params, headers = s.calls[0]
        self.assertIn("/table/v1/driving/106.689372,10.800133;", url)  # đúng thứ tự lon,lat
        self.assertEqual(params, {"annotations": "duration,distance"})
        self.assertIn("User-Agent", headers)
        np.testing.assert_allclose(r.dist_m, self.D, atol=1e-6)
        np.testing.assert_allclose(r.dur_s, self.T, atol=1e-6)
        self.assertTrue((r.nguon == btm.NGUON_OSRM).all())
        # bất đối xứng được giữ nguyên
        self.assertGreater(abs(r.dist_m[0, 1] - r.dist_m[1, 0]), 1.0)

    def test_chunked_requests_give_same_result(self):
        s = FakeOSRMSession()
        sleeps = []
        r = btm.OSRMProvider(max_coords=6, session=s, sleep=sleeps.append, pause_s=1.0).compute(self.locs)
        self.assertEqual(len(s.calls), 16)  # 12 điểm, khối 3 -> 4x4 yêu cầu
        self.assertEqual(len(sleeps), 15)
        for url, params, _ in s.calls:
            n_coords = len(url.split("/table/v1/")[1].split("/", 1)[1].split(";"))
            self.assertLessEqual(n_coords, 6)
        np.testing.assert_allclose(r.dist_m, self.D, atol=1e-6)
        np.testing.assert_allclose(r.dur_s, self.T, atol=1e-6)

    def test_retry_on_503_with_backoff(self):
        s = FakeOSRMSession(fail_first=2)
        sleeps = []
        r = btm.OSRMProvider(session=s, sleep=sleeps.append, retries=3, backoff=2.0).compute(self.locs)
        self.assertEqual(len(s.calls), 3)
        self.assertEqual(sleeps, [2.0, 4.0])
        np.testing.assert_allclose(r.dist_m, self.D, atol=1e-6)

    def test_network_error(self):
        s = FakeOSRMSession(raise_exc=requests.exceptions.ConnectionError("mất mạng"))
        with self.assertRaises(btm.NetworkError):
            btm.OSRMProvider(session=s, sleep=lambda x: None, retries=1).compute(self.locs)
        self.assertEqual(len(s.calls), 2)

    def test_api_error_codes(self):
        with self.assertRaises(btm.ProviderError) as cm:
            btm.OSRMProvider(session=FakeOSRMSession(code="TooBig"), sleep=lambda x: None).compute(self.locs)
        self.assertIn("--osrm-max-coords", str(cm.exception))
        with self.assertRaises(btm.ProviderError):
            btm.OSRMProvider(session=FakeOSRMSession(code="NoTable"), sleep=lambda x: None).compute(self.locs)

    def test_null_pair_filled_and_flagged(self):
        pts = [(round(lo, 6), round(la, 6)) for lo, la in zip(self.locs["kinh_do"], self.locs["vi_do"])]
        s = FakeOSRMSession(null_pairs=[(pts[2], pts[5])])
        r = btm.OSRMProvider(session=s, sleep=lambda x: None).compute(self.locs)
        self.assertTrue(np.isnan(r.dist_m[2, 5]))
        est = btm.EstimateProvider()
        filled = btm.finalize_matrix(r, self.locs, est, strict=False)
        self.assertEqual(filled, [["D01", "D04"]])
        self.assertEqual(r.nguon[2, 5], btm.NGUON_ESTIMATE)
        self.assertEqual(r.nguon[2, 4], btm.NGUON_OSRM)
        self.assertTrue(np.isfinite(r.dist_m).all())
        # chế độ strict phải báo lỗi
        r2 = btm.OSRMProvider(session=s, sleep=lambda x: None).compute(self.locs)
        with self.assertRaises(btm.ProviderError):
            btm.finalize_matrix(r2, self.locs, est, strict=True)

    def test_snap_warning(self):
        p = (round(self.locs.loc[4, "kinh_do"], 6), round(self.locs.loc[4, "vi_do"], 6))
        r = btm.OSRMProvider(session=FakeOSRMSession(snap_override={p: 500.0}), sleep=lambda x: None).compute(self.locs)
        self.assertEqual([w["ma"] for w in r.meta["snap_warnings"]], ["D03"])
        self.assertEqual(r.meta["max_snap_m"], 500.0)


# =========================================================================== 5. Google Routes API
class TestGoogle(unittest.TestCase):
    def setUp(self):
        self.locs = real_locations()
        self.D, self.T = expected_matrix(self.locs, decimals=None)

    def mk(self, session, **kw):
        return btm.GoogleRoutesProvider("KEY-BI-MAT", session=session, sleep=lambda x: None, **kw)

    def test_single_request_and_headers(self):
        s = FakeGoogleSession()
        r = self.mk(s).compute(self.locs)
        self.assertEqual(len(s.calls), 1)
        url, headers, body = s.calls[0]
        self.assertEqual(url, btm.GoogleRoutesProvider.ENDPOINT)
        self.assertEqual(headers["X-Goog-Api-Key"], "KEY-BI-MAT")
        self.assertEqual(headers["X-Goog-FieldMask"], "originIndex,destinationIndex,duration,distanceMeters,status,condition")
        self.assertEqual(body["travelMode"], "DRIVE")
        self.assertEqual(body["routingPreference"], "TRAFFIC_UNAWARE")
        self.assertNotIn("departureTime", body)
        first = body["origins"][0]["waypoint"]["location"]["latLng"]
        self.assertAlmostEqual(first["latitude"], 10.80013297922369)
        self.assertAlmostEqual(first["longitude"], 106.6893717551218)
        # phần tử xáo trộn + bỏ trường 0 vẫn phải ghép đúng ô
        np.testing.assert_allclose(r.dist_m, np.rint(self.D), atol=0.51)
        np.testing.assert_allclose(r.dur_s, np.rint(self.T), atol=0.51)
        self.assertEqual(r.dist_m[3, 3], 0.0)
        self.assertEqual(r.meta["elements_requested"], 144)

    def test_chunking_by_block(self):
        s = FakeGoogleSession()
        r = self.mk(s, block=5).compute(self.locs)
        self.assertEqual(len(s.calls), 9)  # ceil(12/5)=3 khối -> 3x3
        for _, _, body in s.calls:
            self.assertLessEqual(len(body["origins"]) * len(body["destinations"]), 25)
        np.testing.assert_allclose(r.dist_m, np.rint(self.D), atol=0.51)

    def test_missing_route_is_nan(self):
        po = (self.locs.loc[2, "kinh_do"], self.locs.loc[2, "vi_do"])
        pd_ = (self.locs.loc[7, "kinh_do"], self.locs.loc[7, "vi_do"])
        r = self.mk(FakeGoogleSession(missing=[(po, pd_)])).compute(self.locs)
        self.assertTrue(np.isnan(r.dist_m[2, 7]))
        self.assertTrue(np.isnan(r.dur_s[2, 7]))
        self.assertFalse(np.isnan(r.dist_m[7, 2]))

    def test_traffic_aware_departure_time(self):
        dep = datetime.now(timezone.utc) + timedelta(days=2)
        s = FakeGoogleSession()
        self.mk(s, traffic_aware=True, departure_time=dep).compute(self.locs)
        body = s.calls[0][2]
        self.assertEqual(body["routingPreference"], "TRAFFIC_AWARE")
        self.assertRegex(body["departureTime"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_error_response_does_not_leak_key(self):
        err = {"error": {"code": 403, "status": "PERMISSION_DENIED", "message": "Routes API has not been enabled"}}
        with self.assertRaises(btm.ProviderError) as cm:
            self.mk(FakeGoogleSession(error_payload=err, http_status=403)).compute(self.locs)
        self.assertIn("PERMISSION_DENIED", str(cm.exception))
        self.assertNotIn("KEY-BI-MAT", str(cm.exception))

    def test_retry_then_success(self):
        s = FakeGoogleSession(fail_first=1)
        r = self.mk(s).compute(self.locs)
        self.assertEqual(len(s.calls), 2)
        self.assertTrue(np.isfinite(r.dist_m).all())

    def test_parse_duration_and_limits(self):
        self.assertEqual(btm.GoogleRoutesProvider.parse_duration("160s"), 160.0)
        self.assertEqual(btm.GoogleRoutesProvider.parse_duration("1.5s"), 1.5)
        with self.assertRaises(btm.ProviderError):
            btm.GoogleRoutesProvider.parse_duration("2 phút")
        with self.assertRaises(ValueError):
            btm.GoogleRoutesProvider("k", block=26)  # 26*26 = 676 > 625
        with self.assertRaises(btm.ProviderError):
            btm.GoogleRoutesProvider("")


# =========================================================================== 6. Kiểm tra chất lượng
class TestValidate(unittest.TestCase):
    def setUp(self):
        self.locs = real_locations()
        self.ids = self.locs["ma_vi_tri"].tolist()
        self.lat = self.locs["vi_do"].to_numpy(float)
        self.lon = self.locs["kinh_do"].to_numpy(float)

    def good(self):
        r = btm.EstimateProvider().compute(self.locs)
        return np.rint(r.dist_m), np.rint(r.dur_s)

    def test_good_matrix(self):
        d, t = self.good()
        stats, warns = btm.validate_matrix(self.ids, d, t, self.lat, self.lon)
        self.assertEqual(warns, [])
        self.assertEqual(stats["n_pairs"], 132)
        self.assertAlmostEqual(stats["toc_do_tb_kmh"], 25.0, delta=0.2)

    def test_hard_errors(self):
        d, t = self.good()
        bad = d.copy()
        bad[1, 2] = np.nan
        with self.assertRaises(btm.DataError):
            btm.validate_matrix(self.ids, bad, t, self.lat, self.lon)
        bad = d.copy()
        bad[1, 2] = -5
        with self.assertRaises(btm.DataError):
            btm.validate_matrix(self.ids, bad, t, self.lat, self.lon)
        bad = d.copy()
        bad[3, 3] = 10
        with self.assertRaises(btm.DataError):
            btm.validate_matrix(self.ids, bad, t, self.lat, self.lon)
        with self.assertRaises(btm.DataError):
            btm.validate_matrix(self.ids, d[:5, :5], t, self.lat, self.lon)

    def test_abnormal_speed_and_circuity_warn(self):
        d, t = self.good()
        t2 = t.copy()
        t2[2, 3] = d[2, 3] / (2 / 3.6)   # 2 km/h
        d2 = d.copy()
        d2[4, 5] = d[4, 5] * 4           # đường vòng x5.4 so với chim bay
        t2[4, 5] = d2[4, 5] / (25 / 3.6)
        _, warns = btm.validate_matrix(self.ids, d2, t2, self.lat, self.lon)
        self.assertTrue(any("tốc độ" in w and "D01->D02" in w for w in warns), warns)
        self.assertTrue(any("tỉ lệ" in w and "D03->D04" in w for w in warns), warns)

    def test_triangle_violation_is_counted_not_fatal(self):
        d, t = self.good()
        t2 = t.copy()
        t2[2, 3] = t[2, 3] * 5  # đi thẳng 2->3 chậm hơn hẳn đi vòng qua điểm khác
        stats, _ = btm.validate_matrix(self.ids, d, t2, self.lat, self.lon)
        self.assertGreater(stats["vi_pham_tam_giac_thoi_gian"], 0)


# =========================================================================== 7. Chạy từ đầu đến cuối (CLI)
class TestEndToEnd(unittest.TestCase):
    def test_estimate_pipeline_and_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run_cli(["--provider", "estimate", "--out", tmp])
            self.assertEqual(code, 0, err)
            files = {p.name for p in Path(tmp).iterdir()}
            self.assertEqual(files, {"locations.csv", "travel_matrix.csv", "matrix_distance_km.csv",
                                     "matrix_duration_min.csv", "travel_matrix_meta.json",
                                     "GHI_CHU_NGUON_DU_LIEU.md"})
            df = pd.read_csv(Path(tmp) / "travel_matrix.csv", encoding="utf-8-sig")
            self.assertEqual(list(df.columns), tl.MATRIX_COLUMNS)
            self.assertEqual(len(df), 132)
            self.assertFalse((df["ma_di"] == df["ma_den"]).any())
            self.assertEqual(df.duplicated(["ma_di", "ma_den"]).sum(), 0)
            self.assertTrue((df["nguon"] == "uoc_luong").all())
            self.assertTrue((df["khoang_cach_m"] > 0).all() and (df["thoi_gian_s"] > 0).all())
            # BOM cho Excel
            self.assertEqual((Path(tmp) / "travel_matrix.csv").read_bytes()[:3], b"\xef\xbb\xbf")
            meta = json.loads((Path(tmp) / "travel_matrix_meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["provider"], "estimate")
            self.assertEqual(meta["n_pairs"], 132)
            notes = (Path(tmp) / "GHI_CHU_NGUON_DU_LIEU.md").read_text(encoding="utf-8")
            self.assertIn("ƯỚC LƯỢNG", notes)

            # --- travel_lookup
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                tm = tl.TravelMatrix.from_csv(Path(tmp) / "travel_matrix.csv", Path(tmp) / "locations.csv")
            self.assertTrue(any("ƯỚC LƯỢNG" in str(x.message) for x in w))
            self.assertTrue(tm.is_estimate)
            self.assertEqual(tm.ids[:3], ["K01", "K02", "D01"])
            row = df[(df.ma_di == "K01") & (df.ma_den == "D02")].iloc[0]
            self.assertEqual(tm.dist_m("K01", "D02"), row.khoang_cach_m)
            self.assertEqual(tm.time_s("K01", "D02"), row.thoi_gian_s)
            self.assertEqual(tm.dist_m("D02", "D02"), 0)
            tot = tm.route_totals(["K01", "D02", "D03", "K01"])
            self.assertEqual(tot.khoang_cach_m, tm.dist_m("K01", "D02") + tm.dist_m("D02", "D03") + tm.dist_m("D03", "K01"))
            self.assertEqual(len(tot.legs), 3)
            self.assertAlmostEqual(tot.khoang_cach_km, tot.khoang_cach_m / 1000)
            M, S = tm.distance_matrix_m(), tm.time_matrix_s()
            self.assertEqual(M.shape, (12, 12))
            self.assertEqual(M.dtype, np.int64)
            self.assertEqual(M[tm.idx("K01"), tm.idx("D02")], tm.dist_m("K01", "D02"))
            sub_ids = ["D03", "K01", "D02"]
            self.assertEqual(tm.distance_matrix_m(sub_ids)[0, 1], tm.dist_m("D03", "K01"))
            self.assertTrue((tm.time_matrix_min(rounding="ceil") >= tm.time_matrix_min(rounding="floor")).all())
            small = tm.submatrix(["K01", "D02", "D03"])
            self.assertEqual(small.n, 3)
            self.assertEqual(small.dist_m("D02", "D03"), tm.dist_m("D02", "D03"))
            with self.assertRaises(KeyError):
                tm.dist_m("K01", "XYZ")
            with self.assertRaises(ValueError):
                tm.route_totals(["K01"])

    def test_lookup_detects_broken_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli(["--provider", "estimate", "--out", tmp, "--quiet"])
            m = Path(tmp) / "travel_matrix.csv"
            df = pd.read_csv(m, encoding="utf-8-sig")
            df.drop(index=5).to_csv(m, index=False, encoding="utf-8-sig")
            with self.assertRaises(ValueError) as cm:
                tl.TravelMatrix.from_csv(m, Path(tmp) / "locations.csv", warn_if_estimate=False)
            self.assertIn("Thiếu 1 cặp", str(cm.exception))
            pd.concat([df, df.iloc[[0]]]).to_csv(m, index=False, encoding="utf-8-sig")
            with self.assertRaises(ValueError):
                tl.TravelMatrix.from_csv(m, Path(tmp) / "locations.csv", warn_if_estimate=False)

    def test_overwrite_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "travel_matrix_meta.json").write_text(json.dumps({"provider": "osrm"}), encoding="utf-8")
            code, _, err = run_cli(["--provider", "estimate", "--out", tmp, "--quiet"])
            self.assertEqual(code, 2)
            self.assertIn("ĐƯỜNG THỰC", err)
            code, _, _ = run_cli(["--provider", "estimate", "--out", tmp, "--quiet", "--force"])
            self.assertEqual(code, 0)

    def test_osrm_pipeline_with_fake_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = FakeOSRMSession()
            code, out, err = run_cli(["--provider", "osrm", "--out", tmp, "--osrm-pause", "0"], session=s)
            self.assertEqual(code, 0, err)
            meta = json.loads((Path(tmp) / "travel_matrix_meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["provider"], "osrm")
            self.assertEqual(meta["provider_detail"]["n_requests"], 1)
            df = pd.read_csv(Path(tmp) / "travel_matrix.csv", encoding="utf-8-sig")
            self.assertTrue((df["nguon"] == "osrm").all())
            notes = (Path(tmp) / "GHI_CHU_NGUON_DU_LIEU.md").read_text(encoding="utf-8")
            self.assertIn("OpenStreetMap contributors", notes)
            self.assertNotIn("ĐÂY LÀ DỮ LIỆU ƯỚC LƯỢNG", notes)
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                tm = tl.TravelMatrix.from_csv(Path(tmp) / "travel_matrix.csv", Path(tmp) / "locations.csv")
            self.assertFalse(any("ƯỚC LƯỢNG" in str(x.message) for x in w))
            self.assertEqual(tm.provider, "osrm")
            self.assertFalse(tm.is_estimate)

    def test_osrm_network_failure_paths(self):
        boom = requests.exceptions.ConnectionError("không có mạng")
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run_cli(["--provider", "osrm", "--out", tmp, "--retries", "0", "--quiet"],
                                   session=FakeOSRMSession(raise_exc=boom))
            self.assertEqual(code, 3)
            self.assertIn("--fallback-estimate", err)
            self.assertFalse((Path(tmp) / "travel_matrix.csv").exists())  # không ghi file dở dang
            code, _, _ = run_cli(["--provider", "osrm", "--out", tmp, "--retries", "0", "--quiet",
                                  "--fallback-estimate"], session=FakeOSRMSession(raise_exc=boom))
            self.assertEqual(code, 0)
            meta = json.loads((Path(tmp) / "travel_matrix_meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["provider"], "estimate")
            self.assertEqual(meta["fallback_from"], "osrm")

    def test_google_pipeline_small_test_and_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            # thiếu khoá
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("GOOGLE_MAPS_API_KEY", None)
                code, _, err = run_cli(["--provider", "google", "--small-test", "--out", tmp, "--quiet"])
            self.assertEqual(code, 3)
            self.assertIn("GOOGLE_MAPS_API_KEY", err)
            with mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "KEY-BI-MAT"}):
                # chặn khi vượt ngưỡng phần tử
                code, _, err = run_cli(["--provider", "google", "--out", tmp, "--quiet", "--max-elements", "100"])
                self.assertEqual(code, 2)
                self.assertIn("144", err)
                # nhóm nhỏ: 2 kho + 3 điểm giao
                s = FakeGoogleSession()
                code, out, err = run_cli(["--provider", "google", "--small-test", "--out", tmp], session=s)
                self.assertEqual(code, 0, err)
                self.assertNotIn("KEY-BI-MAT", out + err)
            meta = json.loads((Path(tmp) / "travel_matrix_meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["provider"], "google")
            self.assertEqual(meta["n_locations"], 5)
            self.assertEqual(meta["n_pairs"], 20)
            self.assertEqual(meta["provider_detail"]["elements_requested"], 25)
            self.assertNotIn("KEY-BI-MAT", json.dumps(meta))
            notes = (Path(tmp) / "GHI_CHU_NGUON_DU_LIEU.md").read_text(encoding="utf-8")
            self.assertIn("ĐIỀU KHOẢN LƯU TRỮ", notes)
            self.assertEqual(len(pd.read_csv(Path(tmp) / "travel_matrix.csv", encoding="utf-8-sig")), 20)

    def test_bad_parameters_return_error_code(self):
        code, _, err = run_cli(["--provider", "estimate", "--circuity", "0.5", "--out", tempfile.mkdtemp(), "--quiet"])
        self.assertEqual(code, 2)
        code, _, err = run_cli(["--provider", "estimate", "--only", "K01", "--out", tempfile.mkdtemp(), "--quiet"])
        self.assertEqual(code, 2)  # chỉ 1 địa điểm


# =========================================================================== 8. Demo tuyến nhỏ
class TestRouteEvaluation(unittest.TestCase):
    def setUp(self):
        ids = ["K01", "D01", "D02"]
        # phút: K01->D01=10, D01->D02=15, D02->K01=20 (các cặp còn lại điền tuỳ ý)
        dur = np.array([[0, 600, 1500], [600, 0, 900], [1200, 900, 0]], dtype=float)
        dist = np.array([[0, 5000, 8000], [5000, 0, 7000], [9000, 7000, 0]], dtype=float)
        self.tm = tl.TravelMatrix(ids, dist, dur, meta={"provider": "osrm"})
        self.orders = pd.DataFrame({
            "ten_khach_hang": ["A", "B"], "khoi_luong_kg": ["100", "200"], "the_tich_m3": ["1", "2"],
            "thoi_gian_phuc_vu_phut": ["10", "5"], "gio_bat_dau": ["07:00", "06:00"],
            "gio_ket_thuc": ["09:00", "07:30"], "kho_phuc_vu": ["K01;K02", "K01"]}, index=["D01", "D02"])
        self.veh = {"ma_xe": "V01", "ma_kho_quan_ly": "K01", "tai_trong_kg": "500", "the_tich_m3": "10",
                    "gio_bat_dau_ca": "06:00", "gio_ket_thuc_ca": "10:00", "chi_phi_vnd_km": "10000",
                    "chi_phi_co_dinh_vnd": "100000"}

    def test_feasible_route_times_and_cost(self):
        r = demo.evaluate_route(self.tm, self.veh, self.orders, ["D01", "D02"])
        s1, s2 = r["stops"]
        self.assertEqual((s1["den"], s1["cho"], s1["bat_dau"], s1["xong"]), (6 * 3600 + 600, 3000, 7 * 3600, 7 * 3600 + 600))
        self.assertEqual(s2["den"], 7 * 3600 + 600 + 900)           # 07:25
        self.assertEqual(s2["xong"], 7 * 3600 + 1500 + 300)         # 07:30 đúng bằng hạn -> vẫn ĐÚNG
        self.assertTrue(s2["dung_han"])
        self.assertEqual(r["ve_kho"], 7 * 3600 + 1800 + 1200)       # 07:50
        self.assertAlmostEqual(r["km"], 5 + 7 + 9)
        self.assertAlmostEqual(r["chi_phi_vnd"], 100000 + 10000 * 21)
        self.assertEqual(r["tai_kg"], 300)
        self.assertTrue(r["kha_thi"])

    def test_late_overload_and_shift(self):
        self.orders.loc["D02", "gio_ket_thuc"] = "07:29"
        r = demo.evaluate_route(self.tm, self.veh, self.orders, ["D01", "D02"])
        self.assertFalse(r["stops"][1]["dung_han"])
        self.assertFalse(r["kha_thi"])
        self.assertTrue(any("TRỄ HẠN" in n for n in r["ghi_chu"]))

        self.orders.loc["D02", "gio_ket_thuc"] = "07:30"
        veh = dict(self.veh, tai_trong_kg="250")
        r = demo.evaluate_route(self.tm, veh, self.orders, ["D01", "D02"])
        self.assertTrue(any("QUÁ TẢI" in n for n in r["ghi_chu"]))
        self.assertFalse(r["kha_thi"])

        veh = dict(self.veh, gio_ket_thuc_ca="07:40")
        r = demo.evaluate_route(self.tm, veh, self.orders, ["D01", "D02"])
        self.assertTrue(any("hết ca" in n for n in r["ghi_chu"]))

    def test_depot_not_allowed_and_unknown_order(self):
        r = demo.evaluate_route(self.tm, self.veh, self.orders, ["D01"])
        self.assertTrue(r["kha_thi"])
        veh = dict(self.veh, ma_kho_quan_ly="D01")  # D01 không nằm trong kho_phuc_vu của D02
        r = demo.evaluate_route(self.tm, veh, self.orders, ["D02"])
        self.assertTrue(any("kho_phuc_vu" in n for n in r["ghi_chu"]))
        with self.assertRaises(KeyError):
            demo.evaluate_route(self.tm, self.veh, self.orders, ["D99"])

    def test_early_departure_rejected(self):
        with self.assertRaises(ValueError):
            demo.evaluate_route(self.tm, self.veh, self.orders, ["D01"], depart_s=5 * 3600)

    def test_time_helpers(self):
        self.assertEqual(demo.hhmm_to_s("07:30"), 27000)
        self.assertEqual(demo.s_to_hhmm(27000), "07:30")
        self.assertEqual(demo.fmt_vnd(1138808), "1.138.808")


if __name__ == "__main__":
    unittest.main(verbosity=2)
