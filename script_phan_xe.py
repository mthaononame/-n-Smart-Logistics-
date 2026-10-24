import math
import pandas as pd


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
  """Hàm phân xe tự động hỗ trợ 2 chế độ:

  - mode='baseline_3xe': Thuật toán Baseline Tham lam (Kéo theo 3 xe)
  - mode='comparison_2xe': Phương án gom đơn D09 sang V03 kho K02 (Chỉ dùng 2
  xe)
  """
  try:
    depots = pd.read_csv(file_depots)
    vehicles = pd.read_csv(file_vehicles)
    orders = pd.read_csv(file_orders)
  except Exception as e:
    print(f'[LỖI] Không thể đọc file dữ liệu: {e}')
    return

  # Khởi tạo trạng thái lấp đầy của từng xe
  veh_status = {
      v_row['ma_xe']: {
          'kho_quan_ly': v_row['ma_kho_quan_ly'],
          'max_kg': v_row['tai_trong_kg'],
          'max_m3': v_row['the_tich_m3'],
          'current_kg': 0.0,
          'current_m3': 0.0,
          'cost_fixed': v_row['chi_phi_co_dinh_vnd'],
          'orders': [],
      }
      for _, v_row in vehicles.iterrows()
  }

  depot_coords = {
      row['ma_kho']: (row['vi_do'], row['kinh_do'])
      for _, row in depots.iterrows()
  }
  assigned_records, unassigned_records = [], []

  # Lặp qua từng đơn hàng để tiến hành phân bổ
  for _, order in orders.iterrows():
    ma_don = order['ma_don']
    order_kg = order['khoi_luong_kg']
    order_m3 = order['the_tich_m3']
    order_lat, order_lon = order['vi_do'], order['kinh_do']

    # 1. KIỂM TRA CỘT kho_phuc_vu THEO YÊU CẦU CỦA BA/QA
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
          'ly_do_bo_sot': f'Không tìm thấy kho phục vụ hợp lệ ({raw_kho_pv})',
      })
      continue

    # Sắp xếp các kho hợp lệ theo khoảng cách gần nhất
    depot_dist = {
        d_id: haversine(
            order_lat,
            order_lon,
            depot_coords[d_id][0],
            depot_coords[d_id][1],
        )
        for d_id in allowed_depots
    }
    sorted_allowed_depots = sorted(allowed_depots, key=lambda x: depot_dist[x])

    # 2. XÁC ĐỊNH XE ỨNG VIÊN (Tùy theo Kịch bản 3 xe hay 2 xe)
    if mode == 'comparison_2xe' and ma_don == 'D09':
      candidate_vehs = ['V03']  # Ép D09 sang xe V03 thuộc kho K02
    else:
      candidate_vehs = []
      for d_id in sorted_allowed_depots:
        vehs = vehicles[vehicles['ma_kho_quan_ly'] == d_id]['ma_xe'].tolist()
        candidate_vehs.extend(vehs)

    # 3. PHÂN ĐƠN CHO XE ĐẦU TIÊN CÒN ĐỦ SỨC CHỨA
    assigned_veh = None
    for v_code in candidate_vehs:
      st = veh_status[v_code]
      if (st['current_kg'] + order_kg <= st['max_kg']) and (
          st['current_m3'] + order_m3 <= st['max_m3']
      ):
        assigned_veh = v_code
        break

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
          'ly_do_bo_sot': (
              'Vượt quá tải trọng/thể tích của tất cả các xe hợp lệ'
          ),
      })

  # 4. XUẤT FILE VÀ BÁO CÁO CẢNH BÁO
  df_assigned = pd.DataFrame(assigned_records)
  df_unassigned = pd.DataFrame(unassigned_records)

  out_file = (
      'phan_xe_ban_dau.csv'
      if mode == 'baseline_3xe'
      else 'phan_xe_phuong_an_2xe.csv'
  )
  df_assigned.to_csv(out_file, index=False, encoding='utf-8-sig')

  print(f"-> File xuất ra: '{out_file}'")
  if not df_unassigned.empty:
    print('[CẢNH BÁO] Danh sách các đơn chưa được phân (Bị bỏ sót):')
    print(df_unassigned)
  else:
    print('-> Phân bổ 100% thành công, không có đơn hàng bị bỏ sót.\n')

  return df_assigned, df_unassigned, veh_status


if __name__ == '__main__':
  print('=== CHẠY PHƯƠNG ÁN 1: BASELINE (3 XE) ===')
  phan_xe_smart(mode='baseline_3xe')

  print('=== CHẠY PHƯƠNG ÁN 2: SO SÁNH GOM ĐƠN (2 XE) ===')
  phan_xe_smart(mode='comparison_2xe')