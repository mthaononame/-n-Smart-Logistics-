import math
import pandas as pd

# --- KHAI BÁO ĐƯỜNG DẪN DỮ LIỆU ---
DEPOTS_PATH = 'depots.csv'
VEHICLES_PATH = 'vehicles.csv'
ORDERS_PATH = 'orders.csv'

# --- ĐỌC DỮ LIỆU ---
depots = pd.read_csv(DEPOTS_PATH)
vehicles = pd.read_csv(VEHICLES_PATH)
orders = pd.read_csv(ORDERS_PATH)


# Công thức Haversine tính khoảng cách giữa 2 tọa độ GPS (km)
def haversine(lat1, lon1, lat2, lon2):
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


# 2. Lấy tọa độ kho
k01_lat, k01_lon = depots.loc[
    depots['ma_kho'] == 'K01', ['vi_do', 'kinh_do']
].values[0]
k02_lat, k02_lon = depots.loc[
    depots['ma_kho'] == 'K02', ['vi_do', 'kinh_do']
].values[0]

# 3. Khởi tạo trạng thái lấp đầy của các xe
veh_load = {
    v_id: {
        'kg': 0.0,
        'm3': 0.0,
        'kho': k_id,
        'max_kg': max_kg,
        'max_m3': max_m3,
    }
    for v_id, k_id, max_kg, max_m3 in zip(
        vehicles['ma_xe'],
        vehicles['ma_kho_quan_ly'],
        vehicles['tai_trong_kg'],
        vehicles['the_tich_m3'],
    )
}

assigned_rows = []

# 4. Thực thi quy tắc phân xe
for _, order in orders.iterrows():
  # Tính khoảng cách tới 2 kho
  d_k01 = haversine(order['vi_do'], order['kinh_do'], k01_lat, k01_lon)
  d_k02 = haversine(order['vi_do'], order['kinh_do'], k02_lat, k02_lon)

  pref_depot = 'K01' if d_k01 < d_k02 else 'K02'
  alt_depot = 'K02' if pref_depot == 'K01' else 'K01'

  # Danh sách xe ưu tiên theo kho gần nhất
  candidate_vehs = vehicles[vehicles['ma_kho_quan_ly'] == pref_depot][
      'ma_xe'
  ].tolist() + vehicles[vehicles['ma_kho_quan_ly'] == alt_depot]['ma_xe'].tolist()

  assigned_veh = None
  for v in candidate_vehs:
    if (
        veh_load[v]['kg'] + order['khoi_luong_kg'] <= veh_load[v]['max_kg']
    ) and (veh_load[v]['m3'] + order['the_tich_m3'] <= veh_load[v]['max_m3']):
      assigned_veh = v
      break

  if assigned_veh:
    veh_load[assigned_veh]['kg'] += order['khoi_luong_kg']
    veh_load[assigned_veh]['m3'] += order['the_tich_m3']

    assigned_rows.append({
        'ma_don': order['ma_don'],
        'ten_khach_hang': order['ten_khach_hang'],
        'dia_chi': order['dia_chi'],
        'kho_xuat_phat': veh_load[assigned_veh]['kho'],
        'ma_xe_dam_nhan': assigned_veh,
        'khoi_luong_kg': order['khoi_luong_kg'],
        'the_tich_m3': order['the_tich_m3'],
        'thoi_gian_phuc_vu_phut': order['thoi_gian_phuc_vu_phut'],
        'gio_bat_dau': order['gio_bat_dau'],
        'gio_ket_thuc': order['gio_ket_thuc'],
        'tai_trong_luy_ke_kg': round(veh_load[assigned_veh]['kg'], 2),
        'the_tich_luy_ke_m3': round(veh_load[assigned_veh]['m3'], 2),
        'lap_day_tai_trong_%': round(
            (veh_load[assigned_veh]['kg'] / veh_load[assigned_veh]['max_kg'])
            * 100,
            2,
        ),
        'lap_day_the_tich_%': round(
            (veh_load[assigned_veh]['m3'] / veh_load[assigned_veh]['max_m3'])
            * 100,
            2,
        ),
    })

# 5. Xuất file kết quả phan_xe_ban_dau.csv
df_out = pd.DataFrame(assigned_rows)
df_out.to_csv('phan_xe_ban_dau.csv', index=False, encoding='utf-8-sig')
print('Đã xuất thành công file phan_xe_ban_dau.csv!')