"""마일리지 — 잔액·등급·소멸 예정, 적립/사용 내역 (회원 전용)"""
import pandas as pd
import streamlit as st

import db
import ui

ui.title("마일리지")
me = db.require_login("마일리지는 회원 전용입니다. 로그인하면 보유 마일리지와 내역을 볼 수 있습니다.")

acc = db.q(
    "SELECT mileage_id, current_balance, tier FROM mileage_account WHERE member_id = %s",
    (me["member_id"],),
)
if acc.empty:
    st.warning("마일리지 계좌가 없습니다.")
    st.stop()
acc = acc.iloc[0]
mid = int(acc.mileage_id)

summary = db.q(
    """SELECT
         COALESCE(SUM(amount) FILTER (WHERE change_type = 'EARN'), 0) AS earned,
         COALESCE(SUM(remaining_amount) FILTER (
             WHERE change_type = 'EARN' AND remaining_amount > 0
               AND expire_at <= CURRENT_DATE + INTERVAL '1 year'), 0) AS expiring,
         MIN(expire_at) FILTER (WHERE change_type = 'EARN' AND remaining_amount > 0) AS next_expire
       FROM mileage_history WHERE mileage_id = %s""",
    (mid,),
).iloc[0]

c = st.columns(3)
ui.stat_card(c[0], "보유 마일리지", ui.miles(acc.current_balance), f"누적 적립 {ui.miles(summary.earned)}")
ui.stat_card(c[1], "회원 등급", ui.TIER_KO.get(acc.tier, acc.tier), f"다음 등급: {ui.NEXT_TIER.get(acc.tier)}")
note = f"가장 빠른 만료일 {summary.next_expire}" if pd.notna(summary.next_expire) else "소멸 예정 없음"
ui.stat_card(c[2], "1년 내 소멸 예정", ui.miles(summary.expiring), note)

st.write("")
h1, h2 = st.columns([3, 2], vertical_alignment="bottom")
h1.subheader("적립 · 사용 내역")
kind = h2.segmented_control("구분", ["전체", "적립", "사용", "소멸"], default="전체",
                            key="ml_kind", label_visibility="collapsed")

hist = db.q(
    """SELECT h.change_date, h.change_type, h.amount, h.expire_at, h.reason,
              f.flight_number, r.dep_airport_code, r.arr_airport_code
       FROM mileage_history h
       LEFT JOIN booking_segment bs ON h.segment_id = bs.segment_id
       LEFT JOIN flight_schedule fs ON bs.schedule_id = fs.schedule_id
       LEFT JOIN flight f ON fs.flight_number = f.flight_number
       LEFT JOIN route r ON f.route_id = r.route_id
       WHERE h.mileage_id = %s
       ORDER BY h.change_date DESC, h.history_id DESC""",
    (mid,),
)
code = {"적립": "EARN", "사용": "USE", "소멸": "EXPIRE"}.get(kind or "전체")
if code and not hist.empty:
    hist = hist[hist.change_type == code]

if hist.empty:
    with st.container(border=True):
        st.write("내역이 없습니다.")
else:
    def detail(r):
        if pd.notna(r.flight_number):
            return f"{r.flight_number} {r.dep_airport_code} → {r.arr_airport_code}"
        return r.reason or "-"

    badge_kind = {"EARN": "outline", "USE": "dark", "EXPIRE": "muted"}
    ui.table(pd.DataFrame({
        "날짜": hist.change_date.astype(str).str[:10],
        "구분": [ui.badge(ui.CHANGE_KO[t], badge_kind[t]) for t in hist.change_type],
        "내용": [detail(r) for r in hist.itertuples()],
        "마일리지": [("+" if t == "EARN" else "-") + f"{int(a):,}" for t, a in zip(hist.change_type, hist.amount)],
        "만료일": hist.expire_at.astype(str).replace({"None": "-", "NaT": "-"}),
    }), raw_cols=("구분",))
    st.caption("마일리지를 쓸 때는 만료일이 빠른 적립분부터 차감됩니다.")
