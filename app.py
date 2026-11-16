"""
항공기 예약 시스템 — 홈

실행:  streamlit run app.py
"""
import streamlit as st

import db

st.set_page_config(page_title="항공 예약 시스템", page_icon="✈️", layout="wide")

me = db.sidebar_auth()

st.title("항공기 예약 시스템")
st.caption("2026-2학기 데이터베이스설계 · 7분반 6팀")

# 연결 확인 ---------------------------------------------------------------
try:
    counts = db.q(
        """
        SELECT
          (SELECT count(*) FROM airport)         AS 공항,
          (SELECT count(*) FROM flight)          AS 편명,
          (SELECT count(*) FROM flight_schedule) AS 운항스케줄,
          (SELECT count(*) FROM fare)            AS 운임,
          (SELECT count(*) FROM member)          AS 회원,
          (SELECT count(*) FROM booking)         AS 예약
        """
    ).iloc[0]
except Exception as e:
    st.error("데이터베이스에 연결하지 못했습니다.")
    st.code(str(e))
    st.info(
        "로컬에서 실행 중이면 `.streamlit/secrets.toml` 의 접속 정보를 확인하세요. "
        "배포 환경이면 Streamlit Cloud 의 Settings → Secrets 를 확인하세요."
    )
    st.stop()

c = st.columns(6)
for col, (name, val) in zip(c, counts.items()):
    col.metric(name, f"{val:,}")

st.divider()

if me:
    st.success(f"{me['member_name']} 님으로 로그인되어 있습니다.")
else:
    st.info(
        "로그인하지 않아도 항공편 검색과 비회원 예약은 가능합니다. "
        "마일리지는 회원 전용입니다."
    )

st.subheader("화면 구성")
st.markdown(
    """
| 페이지 | 하는 일 | 주요 테이블 |
|---|---|---|
| **항공편 검색** | 출발·도착·날짜로 조회, 운임 등급별 잔여석 | `FLIGHT_SCHEDULE` `FARE` |
| **예약하기** | 탑승객 입력, 좌석 선택, 결제 | `BOOKING` `PASSENGER` `BOOKING_SEGMENT` |
| **예약 조회** | 예약번호 또는 계정으로 조회, 구간 단위 취소 | `BOOKING_SEGMENT` `PAYMENT` |
| **체크인** | 온라인 체크인, 탑승 처리, 마일리지 적립 | `SEAT_ASSIGNMENT` `MILEAGE_HISTORY` |
| **마일리지** | 잔액·이력 조회, 소멸 예정 확인 | `MILEAGE_ACCOUNT` `MILEAGE_HISTORY` |
| **관리자** | 운항 상태 변경, 노선별 탑승률·매출 | 전체 |
"""
)

st.caption("왼쪽 사이드바에서 페이지를 선택하세요.")
