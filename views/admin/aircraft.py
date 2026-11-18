"""관리자 · 항공기·좌석 관리 — 기종(aircraft)과 좌석 배치도(seat)"""
import streamlit as st

import db
import ui

if not db.current_admin():
    st.stop()

S = st.session_state
if "flash_ok" in S:
    st.success(S.pop("flash_ok"))


def _letters(text: str) -> list[str]:
    return [c for c in text.upper() if c.isalpha()]


@st.dialog("항공기 등록", width="large")
def add_dialog():
    with st.form("ac_add", border=False):
        c1, c2 = st.columns(2)
        model = c1.text_input("기종명", placeholder="A330-300")
        maker = c2.text_input("제조사", placeholder="Airbus")
        st.markdown("**비즈니스석**")
        b1, b2, b3 = st.columns(3)
        biz_from = b1.number_input("시작 열", 1, 99, 1, key="ac_bf")
        biz_rows = b2.number_input("열 수 (0이면 없음)", 0, 20, 2, key="ac_br")
        biz_cols = b3.text_input("좌석 문자", "ACDF", key="ac_bc")
        st.markdown("**이코노미석**")
        e1, e2, e3 = st.columns(3)
        eco_from = e1.number_input("시작 열", 1, 99, 10, key="ac_ef")
        eco_rows = e2.number_input("열 수", 1, 80, 25, key="ac_er")
        eco_cols = e3.text_input("좌석 문자", "ABCDEF", key="ac_ec")
        ok = st.form_submit_button("등록", type="primary", width="stretch")
    if ok:
        biz = [f"{r}{c}" for r in range(biz_from, biz_from + biz_rows) for c in _letters(biz_cols)]
        eco = [f"{r}{c}" for r in range(eco_from, eco_from + eco_rows) for c in _letters(eco_cols)]
        if not model.strip():
            st.error("기종명을 입력하세요.")
            return
        if set(biz) & set(eco):
            st.error("비즈니스석과 이코노미석의 열 번호가 겹칩니다.")
            return
        with db.tx() as cur:
            cur.execute(
                "INSERT INTO aircraft (model_name, manufacturer) VALUES (%s, NULLIF(%s, '')) RETURNING aircraft_id",
                (model.strip(), maker.strip()),
            )
            ac_id = cur.fetchone()[0]
            for no in biz:
                cur.execute("INSERT INTO seat (aircraft_id, seat_number, seat_class) VALUES (%s, %s, 'BUSINESS')", (ac_id, no))
            for no in eco:
                cur.execute("INSERT INTO seat (aircraft_id, seat_number, seat_class) VALUES (%s, %s, 'ECONOMY')", (ac_id, no))
        S["flash_ok"] = f"{model.strip()} 항공기를 등록했습니다 (좌석 {len(biz) + len(eco)}석)."
        st.rerun()


h1, h2 = st.columns([4, 1], vertical_alignment="center")
h1.title("항공기·좌석 관리")
if h2.button("+ 항공기 등록", type="primary", width="stretch"):
    add_dialog()

df = db.q(
    """SELECT ac.aircraft_id, ac.model_name, ac.manufacturer,
              count(*) FILTER (WHERE s.seat_class = 'BUSINESS') AS biz,
              count(*) FILTER (WHERE s.seat_class = 'ECONOMY')  AS eco,
              count(s.seat_id) AS total,
              (SELECT count(*) FROM flight_schedule fs WHERE fs.aircraft_id = ac.aircraft_id
                 AND fs.flight_date >= CURRENT_DATE) AS upcoming
       FROM aircraft ac LEFT JOIN seat s ON s.aircraft_id = ac.aircraft_id
       GROUP BY ac.aircraft_id ORDER BY ac.aircraft_id"""
)

left, right = st.columns([1.3, 1], gap="medium")

with left.container(border=True):
    st.subheader("항공기 목록")
    st.caption("행을 선택하면 오른쪽에 좌석 배치가 표시됩니다.")
    view = df.rename(columns={
        "aircraft_id": "번호", "model_name": "기종", "manufacturer": "제조사",
        "biz": "비즈니스석", "eco": "이코노미석", "total": "총 좌석", "upcoming": "예정 운항",
    })
    event = st.dataframe(view, hide_index=True, width="stretch", on_select="rerun",
                         selection_mode="single-row", key="ac_table")

rows = event.selection.rows if event else []
with right.container(border=True):
    if not rows:
        st.subheader("좌석 배치")
        st.caption("왼쪽 목록에서 항공기를 선택하세요.")
    else:
        row = df.iloc[rows[0]]
        st.subheader(f"{row.model_name} 좌석 배치")
        st.caption(f"비즈니스 {row.biz}석 · 이코노미 {row.eco}석 · 총 {row.total}석")
        seats = db.q("SELECT seat_number, seat_class FROM seat WHERE aircraft_id = %s", (int(row.aircraft_id),))
        if seats.empty:
            st.write("등록된 좌석이 없습니다.")
        else:
            st.html(f'<div style="text-align:center">{ui.seat_view_html(seats)}</div>')
