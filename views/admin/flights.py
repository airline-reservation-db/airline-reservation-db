"""관리자 · 항공편 관리 — 정기 편명(flight) 등록·수정·삭제"""
import datetime as dt

import streamlit as st
from psycopg2 import errors as pgerr

import db
import ui

if not db.current_admin():
    st.stop()

S = st.session_state
if "flash_ok" in S:
    st.success(S.pop("flash_ok"))

routes = db.q(
    """SELECT route_id, dep_airport_code || ' → ' || arr_airport_code AS label, flight_duration
       FROM route ORDER BY dep_airport_code, arr_airport_code"""
)
ROUTE_LABEL = dict(zip(routes.route_id, routes.label))
ROUTE_MIN = dict(zip(routes.route_id, routes.flight_duration))


def arr_time(dep: dt.time, route_id: int) -> dt.time:
    return (dt.datetime.combine(dt.date.today(), dep) + dt.timedelta(minutes=int(ROUTE_MIN[route_id]))).time()


@st.dialog("항공편 추가")
def add_dialog():
    with st.form("fl_add", border=False):
        no = st.text_input("편명", placeholder="HS103", max_chars=10)
        rid = st.selectbox("노선", routes.route_id.tolist(), format_func=ROUTE_LABEL.get)
        dep = st.time_input("출발 시각", dt.time(9, 0), step=300)
        ok = st.form_submit_button("추가", type="primary", width="stretch")
    st.caption("도착 시각은 노선의 예상 소요 시간으로 계산합니다.")
    if ok:
        no = no.strip().upper()
        if not no:
            st.error("편명을 입력하세요.")
            return
        try:
            db.execute(
                "INSERT INTO flight (flight_number, route_id, std_dep_time, std_arr_time) VALUES (%s, %s, %s, %s)",
                (no, int(rid), dep, arr_time(dep, int(rid))),
            )
        except pgerr.UniqueViolation:
            st.error("이미 있는 편명입니다.")
            return
        S["flash_ok"] = f"{no} 항공편을 추가했습니다."
        st.rerun()


@st.dialog("항공편 수정")
def edit_dialog(row):
    with st.form("fl_edit", border=False):
        st.text_input("편명", row.flight_number, disabled=True)
        rid = st.selectbox("노선", routes.route_id.tolist(), format_func=ROUTE_LABEL.get,
                           index=routes.route_id.tolist().index(row.route_id))
        dep = st.time_input("출발 시각", row.std_dep_time, step=300)
        ok = st.form_submit_button("저장", type="primary", width="stretch")
    if ok:
        db.execute(
            "UPDATE flight SET route_id = %s, std_dep_time = %s, std_arr_time = %s WHERE flight_number = %s",
            (int(rid), dep, arr_time(dep, int(rid)), row.flight_number),
        )
        S["flash_ok"] = f"{row.flight_number} 항공편을 수정했습니다."
        st.rerun()


@st.dialog("항공편 삭제")
def delete_dialog(row):
    st.write(f"**{row.flight_number}** ({ROUTE_LABEL[row.route_id]}) 항공편을 삭제할까요?")
    if row.schedules:
        st.warning(f"이 편명으로 등록된 운항 스케줄이 {row.schedules}건 있어 삭제할 수 없습니다. "
                   "스케줄을 먼저 정리하세요.")
        return
    if st.button("삭제", type="primary", width="stretch"):
        try:
            db.execute("DELETE FROM flight WHERE flight_number = %s", (row.flight_number,))
        except pgerr.ForeignKeyViolation:
            st.error("다른 데이터가 이 항공편을 참조하고 있어 삭제할 수 없습니다.")
            return
        S["flash_ok"] = f"{row.flight_number} 항공편을 삭제했습니다."
        st.rerun()


h1, h2 = st.columns([4, 1], vertical_alignment="center")
h1.title("항공편 관리")
if h2.button("+ 항공편 추가", type="primary", width="stretch"):
    add_dialog()

with st.container(border=True):
    c1, c2 = st.columns(2)
    q_no = c1.text_input("편명", placeholder="예: HS101")
    q_route = c2.selectbox("노선", [0] + routes.route_id.tolist(),
                           format_func=lambda r: "전체" if r == 0 else ROUTE_LABEL[r])

df = db.q(
    """SELECT f.flight_number, f.route_id, r.dep_airport_code, r.arr_airport_code,
              f.std_dep_time, f.std_arr_time, r.flight_duration,
              (SELECT count(*) FROM flight_schedule fs WHERE fs.flight_number = f.flight_number) AS schedules,
              (SELECT count(*) FROM flight_schedule fs WHERE fs.flight_number = f.flight_number
                 AND fs.flight_date >= CURRENT_DATE) AS upcoming
       FROM flight f JOIN route r ON f.route_id = r.route_id
       WHERE (%s = '' OR f.flight_number ILIKE '%%' || %s || '%%')
         AND (%s = 0 OR f.route_id = %s)
       ORDER BY f.flight_number""",
    (q_no.strip(), q_no.strip(), int(q_route), int(q_route)),
)

view = df.assign(
    출발=df.dep_airport_code, 도착=df.arr_airport_code,
    **{"출발 시각": df.std_dep_time.astype(str).str[:5], "도착 시각": df.std_arr_time.astype(str).str[:5],
       "소요": df.flight_duration.map(ui.duration), "전체 스케줄": df.schedules, "예정 스케줄": df.upcoming},
)[["flight_number", "출발", "도착", "출발 시각", "도착 시각", "소요", "전체 스케줄", "예정 스케줄"]].rename(
    columns={"flight_number": "편명"})

event = st.dataframe(view, hide_index=True, width="stretch", on_select="rerun",
                     selection_mode="single-row", key="fl_table")
st.caption(f"총 {len(df)}건 · 행을 선택하면 수정·삭제할 수 있습니다.")

rows = event.selection.rows if event else []
if rows:
    row = df.iloc[rows[0]]
    c1, c2, _ = st.columns([1, 1, 4])
    if c1.button(f"{row.flight_number} 수정", width="stretch"):
        edit_dialog(row)
    if c2.button(f"{row.flight_number} 삭제", width="stretch"):
        delete_dialog(row)
