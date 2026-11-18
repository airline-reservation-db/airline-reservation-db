"""예약 조회 — 예약번호 + 탑승객 영문 성"""
import streamlit as st

import booking_view
import db
import ui

S = st.session_state

if "flash_ok" in S:
    st.success(S.pop("flash_ok"))

ui.title("예약 조회")

with st.container(border=True):
    with st.form("lookup", border=False):
        c1, c2, c3 = st.columns([1, 1, 1], vertical_alignment="bottom")
        pnr = c1.text_input("예약번호", max_chars=6, placeholder="K7X2MQ")
        last = c2.text_input("탑승객 영문 성", placeholder="HONG")
        ok = c3.form_submit_button("조회하기", type="primary", width="stretch")

if ok:
    found = db.q1(
        """SELECT b.booking_id FROM booking b
           JOIN passenger p ON b.booking_id = p.booking_id
           WHERE b.booking_pnr = %s AND upper(p.last_name) = %s
           LIMIT 1""",
        (pnr.strip().upper(), last.strip().upper()),
    )
    if found:
        S["view_booking"] = int(found)
    else:
        S.pop("view_booking", None)
        st.warning("일치하는 예약이 없습니다. 예약번호와 영문 성을 확인해 주세요.")

me = db.current_member()
if not S.get("view_booking") and me:
    st.caption("회원이라면 마이페이지에서 내 예약 목록을 바로 볼 수 있습니다.")


def _to_checkin(pnr, last):
    S["ci_pnr"], S["ci_last"], S["ci_step"] = pnr, last, 1
    st.switch_page("views/checkin.py")


booking_id = S.get("view_booking")
if booking_id:
    booking_view.render(int(booking_id), on_checkin=_to_checkin)
