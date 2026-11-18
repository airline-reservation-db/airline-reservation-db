"""로그인 — 회원 / 관리자"""
import streamlit as st

import db

_, mid, _ = st.columns([1, 1.4, 1])

with mid:
    with st.container(border=True):
        st.title("로그인")
        member_tab, admin_tab = st.tabs(["회원", "관리자"])

        with member_tab:
            with st.form("login_member", border=False):
                email = st.text_input("이메일", placeholder="hong@example.com")
                pw = st.text_input("비밀번호", type="password")
                ok = st.form_submit_button("로그인", type="primary", width="stretch")
            if ok:
                if db.login(email, pw):
                    st.switch_page("views/search.py")
                else:
                    st.error("이메일 또는 비밀번호가 맞지 않습니다.")

            c1, c2 = st.columns([3, 1], vertical_alignment="center")
            c1.caption("아직 회원이 아니신가요? 비회원도 항공편 예약은 할 수 있어요.")
            if c2.button("회원가입", width="stretch"):
                st.switch_page("views/signup.py")

        with admin_tab:
            if not db.admin_configured():
                st.info("관리자 계정이 설정되어 있지 않습니다.")
            else:
                with st.form("login_admin", border=False):
                    user = st.text_input("관리자 아이디")
                    apw = st.text_input("비밀번호", type="password", key="admin_pw")
                    ok2 = st.form_submit_button("관리자 로그인", type="primary", width="stretch")
                if ok2:
                    if db.admin_login(user, apw):
                        st.rerun()
                    else:
                        st.error("아이디 또는 비밀번호가 맞지 않습니다.")
