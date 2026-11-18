"""회원가입 — member + mileage_account 를 함께 만든다."""
import re

import streamlit as st

import db

_, mid, _ = st.columns([1, 1.6, 1])

with mid:
    with st.container(border=True):
        st.title("회원가입")
        with st.form("signup", border=False):
            name = st.text_input("이름", placeholder="홍길동")
            c1, c2 = st.columns(2)
            email = c1.text_input("이메일", placeholder="hong@example.com")
            phone = c2.text_input("전화번호 (선택)", placeholder="010-1234-5678")
            c3, c4 = st.columns(2)
            pw = c3.text_input("비밀번호", type="password", placeholder="8자 이상, 영문·숫자 조합")
            pw2 = c4.text_input("비밀번호 확인", type="password", placeholder="비밀번호를 다시 입력하세요")
            ok = st.form_submit_button("가입하기", type="primary", width="stretch")

        if ok:
            errors = []
            if not name.strip():
                errors.append("이름을 입력하세요.")
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip()):
                errors.append("이메일 형식이 올바르지 않습니다.")
            elif db.email_taken(email):
                errors.append("이미 가입된 이메일입니다.")
            if len(pw) < 8 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
                errors.append("비밀번호는 8자 이상, 영문과 숫자를 섞어 주세요.")
            elif pw != pw2:
                errors.append("비밀번호 확인이 일치하지 않습니다.")

            if errors:
                for e in errors:
                    st.error(e)
            else:
                try:
                    db.signup(name, email, phone, pw)
                except Exception:
                    st.error("가입 처리 중 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.")
                else:
                    st.switch_page("views/search.py")

        c1, c2 = st.columns([3, 1], vertical_alignment="center")
        c1.caption("이미 계정이 있으신가요?")
        if c2.button("로그인", width="stretch"):
            st.switch_page("views/login.py")
