"""
SKYDB 항공 예약 — 진입점

실행:  streamlit run app.py

로그인 상태에 따라 메뉴가 달라진다.
- 고객: 상단 메뉴 (항공편 검색 · 예약 조회 · 체크인 · 마일리지 · 마이페이지)
- 관리자: 왼쪽 사이드바 콘솔 (대시보드 · 항공편 · 스케줄 · 항공기 · 예약 · 회원)
관리자 계정은 secrets 의 [admin] 에서 읽는다.
"""
from pathlib import Path

import streamlit as st

import db
import ui

st.set_page_config(page_title="SKYDB 항공 예약", page_icon="✈️", layout="wide")
ui.inject_css()

LOGO = str(Path(__file__).parent / "assets" / "logo.svg")
st.logo(LOGO, size="large")


def _logout():
    db.logout()
    st.switch_page("views/search.py")


admin = db.current_admin()
member = db.current_member()

if admin:
    pages = [
        st.Page("views/admin/dashboard.py", title="대시보드", default=True),
        st.Page("views/admin/flights.py", title="항공편 관리"),
        st.Page("views/admin/schedules.py", title="스케줄 관리"),
        st.Page("views/admin/aircraft.py", title="항공기·좌석 관리"),
        st.Page("views/admin/bookings.py", title="예약 관리"),
        st.Page("views/admin/members.py", title="회원 관리"),
    ]
    nav = st.navigation(pages, position="sidebar")
    with st.sidebar:
        st.divider()
        st.caption(f"{admin} 님")
        if st.button("로그아웃", key="admin_logout"):
            db.logout()
            st.rerun()
else:
    pages = [
        st.Page("views/search.py", title="항공편 검색", default=True),
        st.Page("views/lookup.py", title="예약 조회"),
        st.Page("views/checkin.py", title="체크인"),
        st.Page("views/mileage.py", title="마일리지"),
    ]
    if member:
        pages += [
            st.Page("views/mypage.py", title=f"{member['member_name']}님 · 마이페이지"),
            st.Page(_logout, title="로그아웃", url_path="logout"),
        ]
    else:
        pages += [
            st.Page("views/signup.py", title="회원가입"),
            st.Page("views/login.py", title="로그인"),
        ]
    nav = st.navigation(pages, position="top")

nav.run()
