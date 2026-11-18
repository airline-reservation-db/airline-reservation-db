"""관리자 · 예약 관리 — 예약 검색과 상세, 취소"""
import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import booking_view
import db
import ui

if not db.current_admin():
    st.stop()

S = st.session_state
TODAY = dt.datetime.now(ZoneInfo("Asia/Seoul")).date()
if "flash_ok" in S:
    st.success(S.pop("flash_ok"))

st.title("예약 관리")

with st.container(border=True):
    c1, c2, c3 = st.columns([2, 1, 2])
    kw = c1.text_input("예약번호 · 이메일 · 탑승객 성", placeholder="예: K7X2MQ")
    status = c2.selectbox("상태", ["", "TICKETED", "PENDING", "CONFIRMED", "CANCELLED"],
                          format_func=lambda s: "전체" if not s else ui.BOOKING_KO[s])
    period = c3.date_input("예약일", (TODAY - dt.timedelta(days=30), TODAY))

d1, d2 = (period if isinstance(period, tuple) and len(period) == 2 else (TODAY - dt.timedelta(days=30), TODAY))

df = db.q(
    """SELECT b.booking_id, b.booking_pnr, b.booking_date, b.total_price, b.booking_status,
              b.contact_email, COALESCE(m.member_name, '비회원') AS booker,
              (SELECT string_agg(f.flight_number || ' ' || r.dep_airport_code || '→' || r.arr_airport_code
                                 || ' ' || to_char(fs.flight_date, 'MM-DD'), ', ' ORDER BY bs.segment_order)
                 FROM booking_segment bs
                 JOIN flight_schedule fs ON bs.schedule_id = fs.schedule_id
                 JOIN flight f ON fs.flight_number = f.flight_number
                 JOIN route r ON f.route_id = r.route_id
                WHERE bs.booking_id = b.booking_id) AS trip,
              (SELECT count(*) FROM passenger p WHERE p.booking_id = b.booking_id) AS pax
       FROM booking b LEFT JOIN member m ON b.member_id = m.member_id
       WHERE b.booking_date::date BETWEEN %s AND %s
         AND (%s = '' OR b.booking_status = %s)
         AND (%s = '' OR b.booking_pnr ILIKE %s OR b.contact_email ILIKE %s
              OR EXISTS (SELECT 1 FROM passenger p WHERE p.booking_id = b.booking_id AND p.last_name ILIKE %s))
       ORDER BY b.booking_date DESC""",
    (d1, d2, status, status, kw.strip(), f"%{kw.strip()}%", f"%{kw.strip()}%", f"%{kw.strip()}%"),
)

if df.empty:
    with st.container(border=True):
        st.write("조건에 맞는 예약이 없습니다.")
    st.stop()

view = pd.DataFrame({
    "예약번호": df.booking_pnr,
    "예약자": df.booker,
    "연락처": df.contact_email,
    "여정": df.trip,
    "인원": df.pax,
    "예약일": df.booking_date.astype(str).str[:16],
    "금액": df.total_price.map(lambda v: f"{int(v):,}"),
    "상태": df.booking_status.map(ui.BOOKING_KO),
})
event = st.dataframe(view, hide_index=True, width="stretch", on_select="rerun",
                     selection_mode="single-row", key="bk_table")
st.caption(f"총 {len(df)}건 · 행을 선택하면 상세를 볼 수 있습니다.")

rows = event.selection.rows if event else []
if rows:
    booking_view.render(int(df.iloc[rows[0]].booking_id), admin=True)
