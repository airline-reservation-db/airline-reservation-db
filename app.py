"""
항공기 예약 시스템 — 진입점

실행:  streamlit run app.py

사용자에게 보이는 메뉴만 여기서 등록한다.
관리자 화면(pages/6_관리자.py)은 파일은 남겨두되 메뉴에서는 뺐다.
"""
import streamlit as st

pg = st.navigation(
    [
        st.Page("pages/1_항공편_검색.py", title="항공편 검색", icon="🔍", default=True),
        st.Page("pages/2_예약하기.py", title="예약하기", icon="🎫"),
        st.Page("pages/3_예약_조회.py", title="예약 조회", icon="📋"),
        st.Page("pages/4_체크인.py", title="체크인", icon="🛂"),
        st.Page("pages/5_마일리지.py", title="마일리지", icon="💳"),
    ]
)
pg.run()
