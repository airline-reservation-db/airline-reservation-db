"""
항공편 검색 — 운임 등급별 가격과 잔여석

담당: 운항·운임 도메인
핵심: 잔여석은 좌석 배정이 아니라 FARE의 배정/판매 좌석 수로 구한다.
"""
import datetime as dt

import streamlit as st

import db

st.set_page_config(page_title="항공편 검색", page_icon="🔍", layout="wide")

me = db.sidebar_auth()
st.title("항공편 검색")

opts = db.airport_options()
names = list(opts.keys())

c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
dep_label = c1.selectbox("출발지", names, index=names.index("인천 (ICN)") if "인천 (ICN)" in names else 0)
arr_label = c2.selectbox("도착지", names, index=names.index("후쿠오카 (FUK)") if "후쿠오카 (FUK)" in names else 1)
date = c3.date_input("출발일", dt.date.today() + dt.timedelta(days=7))
pax = c4.number_input("인원", 1, 9, 1)

dep, arr = opts[dep_label], opts[arr_label]

if dep == arr:
    st.warning("출발지와 도착지가 같습니다.")
    st.stop()

SEARCH = """
SELECT fs.schedule_id,
       f.flight_number,
       f.std_dep_time,
       f.std_arr_time,
       ac.model_name,
       fs.flight_status,
       fs.terminal,
       fs.gate,
       r.distance_km,
       fa.fare_id,
       fa.seat_class,
       fa.fare_code,
       fa.base_price,
       fa.cancellation_fee,
       fa.mileage_rate,
       fa.seats_allotted,
       fa.seats_sold,
       fa.seats_allotted - fa.seats_sold AS seats_left
FROM flight_schedule fs
JOIN flight   f  ON fs.flight_number = f.flight_number
JOIN route    r  ON f.route_id       = r.route_id
JOIN aircraft ac ON fs.aircraft_id   = ac.aircraft_id
JOIN fare     fa ON fa.schedule_id   = fs.schedule_id
WHERE r.dep_airport_code = %s
  AND r.arr_airport_code = %s
  AND fs.flight_date     = %s
  AND fs.flight_status  <> 'CANCELLED'
ORDER BY f.std_dep_time, fa.seat_class DESC, fa.base_price
"""

rows = db.q(SEARCH, (dep, arr, date))

if rows.empty:
    st.info("조건에 맞는 항공편이 없습니다. 날짜나 구간을 바꿔보세요.")
    st.stop()

st.caption(f"{dep_label} → {arr_label} · {date} · {rows['flight_number'].nunique()}편")

CLASS_KO = {"ECONOMY": "이코노미", "BUSINESS": "비즈니스", "FIRST": "퍼스트"}
CODE_KO = {"Y": "정규", "M": "할인", "Q": "특가", "C": "정규"}
STATUS_KO = {"SCHEDULED": "운항예정", "DELAYED": "지연", "COMPLETED": "운항완료"}

for flight_no, g in rows.groupby("flight_number", sort=False):
    head = g.iloc[0]
    with st.container(border=True):
        a, b, c = st.columns([2, 3, 2])
        a.markdown(f"### {flight_no}")
        a.caption(f"{head.model_name} · {head.distance_km:,}km")
        b.markdown(
            f"**{str(head.std_dep_time)[:5]} → {str(head.std_arr_time)[:5]}**"
        )
        gate = f" · 탑승구 {head.gate}" if head.gate else ""
        b.caption(f"{dep} → {arr}{gate}")
        status = STATUS_KO.get(head.flight_status, head.flight_status)
        c.markdown(f"**{status}**")
        if head.terminal:
            c.caption(f"터미널 {head.terminal}")

        st.write("")
        for fare in g.itertuples():
            left = fare.seats_left
            sold_out = left <= 0
            not_enough = (not sold_out) and left < pax

            f1, f2, f3, f4, f5 = st.columns([2, 2, 2, 2, 1.4])
            f1.write(f"{CLASS_KO.get(fare.seat_class, fare.seat_class)}")
            f2.write(f"`{fare.fare_code}` {CODE_KO.get(fare.fare_code, '')}")
            f3.write(db.won(fare.base_price))

            if sold_out:
                f4.write(":gray[매진]")
            elif not_enough:
                f4.write(f":orange[{left}석] · 인원 부족")
            elif left <= 10:
                f4.write(f":orange[{left}석]")
            else:
                f4.write(f"{left}석")

            disabled = sold_out or not_enough
            if f5.button("선택", key=f"pick{fare.fare_id}", disabled=disabled,
                         use_container_width=True):
                st.session_state["picked"] = {
                    "schedule_id": int(fare.schedule_id),
                    "fare_id": int(fare.fare_id),
                    "flight_number": flight_no,
                    "flight_date": str(date),
                    "dep": dep,
                    "arr": arr,
                    "seat_class": fare.seat_class,
                    "fare_code": fare.fare_code,
                    "base_price": int(fare.base_price),
                    "pax": int(pax),
                }
                st.success(
                    f"{flight_no} {fare.fare_code} 운임을 담았습니다. "
                    "왼쪽 **예약하기** 페이지로 이동하세요."
                )
