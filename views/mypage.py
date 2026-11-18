"""마이페이지 — 회원 정보, 내 예약 목록"""
import streamlit as st

import db
import ui

S = st.session_state
me = db.require_login()

info = db.q(
    """SELECT m.member_name, m.email, m.phone, m.join_date, ma.tier, ma.current_balance
       FROM member m LEFT JOIN mileage_account ma ON m.member_id = ma.member_id
       WHERE m.member_id = %s""",
    (me["member_id"],),
).iloc[0]


@st.dialog("회원 정보 수정")
def edit_profile():
    with st.form("profile", border=False):
        name = st.text_input("이름", info.member_name)
        phone = st.text_input("전화번호", info.phone or "")
        ok = st.form_submit_button("저장", type="primary", width="stretch")
    if ok:
        if not name.strip():
            st.error("이름을 입력하세요.")
            return
        db.execute(
            "UPDATE member SET member_name = %s, phone = NULLIF(%s, '') WHERE member_id = %s",
            (name.strip(), phone.strip(), me["member_id"]),
        )
        S["member"]["member_name"] = name.strip()
        st.rerun()


h1, h2 = st.columns([4, 1], vertical_alignment="center")
h1.title("마이페이지")
if h2.button("회원 정보 수정", width="stretch"):
    edit_profile()

c = st.columns(3)
ui.stat_card(c[0], "이름", info.member_name, f"{info.email}" + (f" · {info.phone}" if info.phone else ""))
ui.stat_card(c[1], "회원 등급", ui.TIER_KO.get(info.tier, info.tier or "-"), f"다음 등급: {ui.NEXT_TIER.get(info.tier, '-')}")
with c[2].container(border=True):
    ui.stat("보유 마일리지", ui.miles(info.current_balance))
    if st.button("마일리지 내역 보기 →", type="tertiary"):
        st.switch_page("views/mileage.py")

st.subheader("내 예약 목록")
mine = db.q(
    """SELECT b.booking_id, b.booking_pnr, b.booking_status,
              string_agg(r.dep_airport_code || ' → ' || r.arr_airport_code || ' (' || f.flight_number || ')',
                         ', ' ORDER BY bs.segment_order) AS trip,
              MIN(fs.flight_date) AS dep_date,
              bool_and(bs.segment_status = 'FLOWN') AS flown,
              EXISTS (SELECT 1 FROM seat_assignment sa JOIN booking_segment s2 ON sa.segment_id = s2.segment_id
                      WHERE s2.booking_id = b.booking_id AND s2.segment_status = 'ACTIVE'
                        AND sa.checked_in_at IS NOT NULL) AS checked
       FROM booking b
       JOIN booking_segment bs ON b.booking_id = bs.booking_id
       JOIN flight_schedule fs ON bs.schedule_id = fs.schedule_id
       JOIN flight f ON fs.flight_number = f.flight_number
       JOIN route r ON f.route_id = r.route_id
       WHERE b.member_id = %s
       GROUP BY b.booking_id
       ORDER BY MIN(fs.flight_date) DESC""",
    (me["member_id"],),
)

if mine.empty:
    with st.container(border=True):
        st.write("아직 예약이 없습니다.")
        if st.button("항공편 검색하기", type="primary"):
            st.switch_page("views/search.py")
else:
    with st.container(border=True):
        hd = st.columns([1.2, 3, 1.2, 1.2, 0.8])
        for col, t in zip(hd, ["예약번호", "여정", "출발일", "상태", ""]):
            col.caption(t)
        for r in mine.itertuples():
            cols = st.columns([1.2, 3, 1.2, 1.2, 0.8], vertical_alignment="center")
            cols[0].write(f"**{r.booking_pnr}**")
            cols[1].write(r.trip)
            cols[2].write(str(r.dep_date))
            cols[3].html(ui.booking_badge(r.booking_status, bool(r.checked), bool(r.flown)))
            if cols[4].button("상세", key=f"my_{r.booking_id}", width="stretch"):
                S["view_booking"] = int(r.booking_id)
                st.switch_page("views/lookup.py")
