import math
import os
import pandas as pd

# Đường dẫn thư mục chứa file code
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def haversine(lat1, lon1, lat2, lon2):
  """Tính khoảng cách Haversine giữa 2 tọa độ GPS (km)"""
  R = 6371.0
  dlat = math.radians(lat2 - lat1)
  dlon = math.radians(lon2 - lon1)
  a = (
      math.sin(dlat / 2) ** 2
      + math.cos(math.radians(lat1))
      * math.cos(math.radians(lat2))
      * math.sin(dlon / 2) ** 2
  )
  return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def phan_xe_smart(
    file_depots='depots.csv',
    file_vehicles='vehicles.csv',
    file_orders='orders.csv',
    mode='baseline_3xe',
):
  path_depots = os.path.join(BASE_DIR, file_depots)
  path_vehicles = os.path.join(BASE_DIR, file_vehicles)
  path_orders = os.path.join(BASE_DIR, file_orders)

  # 1. Nạp dữ liệu
  try:
    depots = pd.read_csv(path_depots)
    vehicles = pd.read_csv(path_vehicles)
    orders = pd.read_csv(path_orders)
  except Exception as e:
    print(f'[LỖI CRITICAL] Không thể đọc file dữ liệu: {e}')
    return None, None, None

  # Khởi tạo trạng thái từng xe
  veh_status = {
      v_row['ma_xe']: {
          'kho_quan_ly': v_row['ma_kho_quan_ly'],
          'max_kg': v_row['tai_trong_kg'],
          'max_m3': v_row['the_tich_m3'],
          'current_kg': 0.0,
          'current_m3': 0.0,
          'orders': [],
      }
      for _, v_row in vehicles.iterrows()
  }

  depot_coords = {
      row['ma_kho']: (row['vi_do'], row['kinh_do'])
      for _, row in depots.iterrows()
  }

  assigned_records = []
  unassigned_records = []

  # 2. Xử lý từng đơn hàng
  for _, order in orders.iterrows():
    ma_don = order['ma_don']
    order_kg = float(order['khoi_luong_kg'])
    order_m3 = float(order['the_tich_m3'])
    order_lat, order_lon = float(order['vi_do']), float(order['kinh_do'])

    # Kiểm tra cột kho_phuc_vu
    raw_kho_pv = str(order['kho_phuc_vu'])
    allowed_depots = [
        k.strip() for k in raw_kho_pv.split(';') if k.strip() in depot_coords
    ]

    if not allowed_depots:
      unassigned_records.append({
          'ma_don': ma_don,
          'ten_khach_hang': order['ten_khach_hang'],
          'khoi_luong_kg': order_kg,
          'the_tich_m3': order_m3,
          'ly_do_tu_choi': (
              f"Kho phục vụ '{raw_kho_pv}' không hợp lệ trong depots.csv"
          ),
      })
      continue

    # Tính khoảng cách tới kho cho phép & sắp xếp
    depot_dist = {
        d_id: haversine(
            order_lat,
            order_lon,
            depot_coords[d_id][0],
            depot_coords[d_id][1],
        )
        for d_id in allowed_depots
    }
    sorted_allowed_depots = sorted(allowed_depots, key=lambda d: depot_dist[d])

    # Chọn danh sách xe ứng viên theo kịch bản
    if mode == 'comparison_2xe' and ma_don == 'D09':
      candidate_vehs = ['V03']
    else:
      candidate_vehs = []
      for d_id in sorted_allowed_depots:
        vehs = vehicles[vehicles['ma_kho_quan_ly'] == d_id]['ma_xe'].tolist()
        candidate_vehs.extend(vehs)

    # Thử gán xe
    assigned_veh = None
    failed_logs = []

    for v_code in candidate_vehs:
      st = veh_status[v_code]
      remain_kg = st['max_kg'] - st['current_kg']
      remain_m3 = st['max_m3'] - st['current_m3']

      if order_kg <= remain_kg and order_m3 <= remain_m3:
        assigned_veh = v_code
        break
      else:
        failed_logs.append(
            f'Xe {v_code} (Kho {st["kho_quan_ly"]}): Dư {remain_kg:.1f}kg /'
            f' {remain_m3:.2f}m3'
        )

    if assigned_veh:
      st = veh_status[assigned_veh]
      st['current_kg'] += order_kg
      st['current_m3'] += order_m3
      st['orders'].append(ma_don)

      assigned_records.append({
          'ma_don': ma_don,
          'ten_khach_hang': order['ten_khach_hang'],
          'dia_chi': order['dia_chi'],
          'kho_phuc_vu_cho_phep': raw_kho_pv,
          'kho_xuat_phat': st['kho_quan_ly'],
          'ma_xe_dam_nhan': assigned_veh,
          'khoi_luong_kg': order_kg,
          'the_tich_m3': order_m3,
          'thoi_gian_phuc_vu_phut': order['thoi_gian_phuc_vu_phut'],
          'gio_bat_dau': order['gio_bat_dau'],
          'gio_ket_thuc': order['gio_ket_thuc'],
          'tai_trong_luy_ke_kg': round(st['current_kg'], 2),
          'the_tich_luy_ke_m3': round(st['current_m3'], 2),
          'muc_su_dung_tai_trong_%': round(
              (st['current_kg'] / st['max_kg']) * 100, 2
          ),
          'muc_su_dung_the_tich_%': round(
              (st['current_m3'] / st['max_m3']) * 100, 2
          ),
      })
    else:
      unassigned_records.append({
          'ma_don': ma_don,
          'ten_khach_hang': order['ten_khach_hang'],
          'khoi_luong_kg': order_kg,
          'the_tich_m3': order_m3,
          'ly_do_tu_choi': (
              f'Các xe đều quá tải: {"; ".join(failed_logs)}'
          ),
      })

  # 3. Xuất file kết quả
  df_assigned = pd.DataFrame(assigned_records)
  df_unassigned = pd.DataFrame(unassigned_records)

  out_filename = (
      'phan_xe_ban_dau.csv'
      if mode == 'baseline_3xe'
      else 'phan_xe_phuong_an_2xe.csv'
  )
  out_path = os.path.join(BASE_DIR, out_filename)
  df_assigned.to_csv(out_path, index=False, encoding='utf-8-sig')

  # In câu thông báo chuẩn của code cũ
  print(f"-> File xuất ra: '{out_filename}'")
  if not df_unassigned.empty:
    print('[CẢNH BÁO] CÓ ĐƠN HÀNG CHƯA ĐƯỢC PHÂN:')
    print(df_unassigned)
  else:
    print(
        '-> Phân bổ 100% thành công, không có đơn hàng bị bỏ sót.\n'
    )

  return df_assigned, df_unassigned, veh_status


if __name__ == '__main__':
  print('=== CHẠY PHƯƠNG ÁN 1: BASELINE (3 XE) ===')
  df1, un1, st1 = phan_xe_smart(mode='baseline_3xe')

  print('=== CHẠY PHƯƠNG ÁN 2: SO SÁNH GOM ĐƠN (2 XE) ===')
  df2, un2, st2 = phan_xe_smart(mode='comparison_2xe')