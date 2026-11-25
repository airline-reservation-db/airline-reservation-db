"""관리자 · 스케줄 관리 — 날짜별 운항(flight_schedule), 탑승 처리, 운항 완료"""
import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from psycopg2 import errors as pgerr

import db
import services
import ui

if not db.current_admin():
    st.stop()

S = st.session_state
TODAY = dt.datetime.now(ZoneInfo("Asia/Seoul")).date()
if "flash_ok" in S:
    st.success(S.pop("flash_ok"))

flights = db.q(
    """SELECT f.flight_number, r.dep_airport_code || ' → ' || r.arr_airport_code AS label
       FROM flight f JOIN route r ON f.route_id = r.route_id ORDER BY f.flight_number"""
)
FL_LABEL = {r.flight_number: f"{r.flight_number} · {r.label}" for r in flights.itertuples()}
aircraft = db.q("SELECT aircraft_id, model_name FROM aircraft ORDER BY aircraft_id")
AC_LABEL = {int(r.aircraft_id): f"{r.model_name} (#{r.aircraft_id})" for r in aircraft.itertuples()}
STATUSES = ["SCHEDULED", "DELAYED", "CANCELLED", "COMPLETED"]


@st.dialog("스케줄 추가")
def add_dialog():
    with st.form("sc_add", border=False):
        fno = st.selectbox("편명", list(FL_LABEL), format_func=FL_LABEL.get)
        day = st.date_input("운항일", TODAY + dt.timedelta(days=1))
        ac = st.selectbox("기종", list(AC_LABEL), format_func=AC_LABEL.get)
        c1, c2 = st.columns(2)
        term = c1.text_input("터미널", "T1")
        gate = c2.text_input("탑승구", "")
        ok = st.form_submit_button("추가", type="primary", width="stretch")
    st.caption("운임은 같은 편명의 가장 최근 스케줄 운임표를 그대로 복사합니다(판매석 0).")
    if ok:
        try:
            with db.tx() as cur:
                cur.execute(
                    """INSERT INTO flight_schedule (flight_number, aircraft_id, flight_date, terminal, gate)
                       VALUES (%s, %s, %s, NULLIF(%s, ''), NULLIF(%s, ''))
                       RETURNING schedule_id""",
                    (fno, int(ac), day, term.strip(), gate.strip()),
                )
                sid = cur.fetchone()[0]
                cur.execute(
                    """INSERT INTO fare (schedule_id, seat_class, fare_code, base_price, seats_allotted,
                                         seats_sold, cancellation_fee, mileage_rate)
                       SELECT %s, seat_class, fare_code, base_price, seats_allotted, 0,
                              cancellation_fee, mileage_rate
                       FROM fare
                       WHERE schedule_id = (SELECT schedule_id FROM flight_schedule
                                            WHERE flight_number = %s AND schedule_id <> %s
                                            ORDER BY flight_date DESC LIMIT 1)""",
                    (sid, fno, sid),
                )
                if cur.rowcount == 0:
                    raise ValueError("no fare template")
        except pgerr.UniqueViolation:
            st.error("같은 날짜에 이미 등록된 편명입니다.")
            return
        except ValueError:
            st.error("복사할 운임표가 없습니다. 이 편명의 기존 스케줄이 하나 이상 있어야 합니다.")
            return
        S["flash_ok"] = f"{fno} {day} 스케줄을 추가했습니다."
        st.rerun()


@st.dialog("스케줄 수정")
def edit_dialog(row):
    st.write(f"**{row.flight_number}** · {row.route} · {ui.kdate(row.flight_date)}")
    with st.form("sc_edit", border=False):
        status = st.selectbox("운항 상태", STATUSES, index=STATUSES.index(row.flight_status),
                              format_func=ui.FLIGHT_KO.get)
        ac = st.selectbox("기종", list(AC_LABEL), index=list(AC_LABEL).index(int(row.aircraft_id)),
                          format_func=AC_LABEL.get)
        c1, c2 = st.columns(2)
        term = c1.text_input("터미널", row.terminal or "")
        gate = c2.text_input("탑승구", row.gate or "")
        ok = st.form_submit_button("저장", type="primary", width="stretch")
    affected = db.q(
        """SELECT b.booking_pnr AS 예약번호, b.contact_email AS 연락처, count(sa.seat_assign_id) AS 좌석수
           FROM booking_segment bs JOIN booking b ON bs.booking_id = b.booking_id
           LEFT JOIN seat_assignment sa ON bs.segment_id = sa.segment_id
           WHERE bs.schedule_id = %s AND bs.segment_status = 'ACTIVE'
           GROUP BY b.booking_pnr, b.contact_email""",
        (int(row.schedule_id),),
    )
    if not affected.empty:
        st.caption(f"이 편에 유효한 예약 {len(affected)}건이 있습니다. 결항·기종 변경 시 안내가 필요합니다.")
        st.dataframe(affected, hide_index=True, width="stretch", height=min(35 * (len(affected) + 1) + 3, 220))
    if ok:
        if int(ac) != int(row.aircraft_id) and not affected.empty:
            st.error("좌석이 배정된 예약이 있어 기종을 바꿀 수 없습니다.")
            return
        db.execute(
            """UPDATE flight_schedule SET flight_status = %s, aircraft_id = %s,
                      terminal = NULLIF(%s, ''), gate = NULLIF(%s, '')
               WHERE schedule_id = %s""",
            (status, int(ac), term.strip(), gate.strip(), int(row.schedule_id)),
        )
        S["flash_ok"] = f"{row.flight_number} {row.flight_date} 스케줄을 수정했습니다."
        st.rerun()


@st.dialog("스케줄 삭제")
def delete_dialog(row):
    st.write(f"**{row.flight_number}** · {row.route} · {ui.kdate(row.flight_date)} 스케줄을 삭제할까요?")
    if row.booked:
        st.warning("예약이 연결된 스케줄은 삭제할 수 없습니다. 결항 처리를 이용하세요.")
        return
    if st.button("삭제", type="primary", width="stretch"):
        try:
            with db.tx() as cur:
                cur.execute("DELETE FROM fare WHERE schedule_id = %s", (int(row.schedule_id),))
                cur.execute("DELETE FROM flight_schedule WHERE schedule_id = %s", (int(row.schedule_id),))
        except pgerr.ForeignKeyViolation:
            st.error("다른 데이터가 이 스케줄을 참조하고 있어 삭제할 수 없습니다.")
            return
        S["flash_ok"] = "스케줄을 삭제했습니다."
        st.rerun()


# ---------------------------------------------------------------- 목록

h1, h2 = st.columns([4, 1], vertical_alignment="center")
h1.title("스케줄 관리")
if h2.button("+ 스케줄 추가", type="primary", width="stretch"):
    add_dialog()

with st.container(border=True):
    c1, c2, c3 = st.columns(3)
    q_fl = c1.selectbox("편명", [""] + list(FL_LABEL), format_func=lambda f: "전체" if not f else FL_LABEL[f])
    q_day = c2.date_input("운항일", TODAY)
    q_status = c3.selectbox("운항 상태", [""] + STATUSES, format_func=lambda s: "전체" if not s else ui.FLIGHT_KO[s])

df = db.q(
    """SELECT fs.schedule_id, fs.flight_number, fs.flight_date, fs.flight_status, fs.aircraft_id,
              fs.terminal, fs.gate, ac.model_name,
              r.dep_airport_code || ' → ' || r.arr_airport_code AS route,
              f.std_dep_time, f.std_arr_time,
              -- 실제 빈 좌석 수 (운임 할당이 좌석 수보다 많게 잡힌 기종이 있어 좌석 기준으로 센다)
              (SELECT count(*) FROM seat s WHERE s.aircraft_id = fs.aircraft_id)
                - (SELECT count(*) FROM booking_segment bs JOIN seat_assignment sa ON sa.segment_id = bs.segment_id
                    WHERE bs.schedule_id = fs.schedule_id AND bs.segment_status <> 'CANCELLED') AS seats_left,
              (SELECT count(*) FROM booking_segment bs WHERE bs.schedule_id = fs.schedule_id) AS booked,
              (SELECT count(*) FROM booking_segment bs JOIN seat_assignment sa ON sa.segment_id = bs.segment_id
                WHERE bs.schedule_id = fs.schedule_id AND bs.segment_status <> 'CANCELLED') AS pax
       FROM flight_schedule fs
       JOIN flight f ON fs.flight_number = f.flight_number
       JOIN route r ON f.route_id = r.route_id
       JOIN aircraft ac ON fs.aircraft_id = ac.aircraft_id
       WHERE fs.flight_date = %s
         AND (%s = '' OR fs.flight_number = %s)
         AND (%s = '' OR fs.flight_status = %s)
       ORDER BY f.std_dep_time""",
    (q_day, q_fl, q_fl, q_status, q_status),
)

view = pd.DataFrame({
    "편명": df.flight_number,
    "노선": df.route,
    "출발": df.std_dep_time.astype(str).str[:5],
    "도착": df.std_arr_time.astype(str).str[:5],
    "기종": df.model_name,
    "운항 상태": df.flight_status.map(ui.FLIGHT_KO),
    "터미널": df.terminal.fillna("-"),
    "탑승구": df.gate.fillna("-"),
    "탑승객": df.pax,
    "잔여석": df.seats_left,
}) if not df.empty else pd.DataFrame()

if df.empty:
    with st.container(border=True):
        st.write("해당 조건의 스케줄이 없습니다.")
    st.stop()

event = st.dataframe(view, hide_index=True, width="stretch", on_select="rerun",
                     selection_mode="single-row", key="sc_table")
st.caption(f"총 {len(df)}건 · 행을 선택하면 수정·삭제와 탑승 관리를 할 수 있습니다.")

rows = event.selection.rows if event else []
if not rows:
    st.stop()

row = df.iloc[rows[0]]
c1, c2, _ = st.columns([1, 1, 4])
if c1.button("수정", width="stretch"):
    edit_dialog(row)
if c2.button("삭제", width="stretch"):
    delete_dialog(row)

# ---------------------------------------------------------------- 탑승 관리
st.subheader(f"{row.flight_number} 탑승 관리")
manifest = db.q(
    """SELECT sa.seat_assign_id, b.booking_pnr, p.last_name || '/' || p.first_name AS name,
              st.seat_number, sa.checked_in_at IS NOT NULL AS checked, sa.is_boarded,
              p.member_id IS NOT NULL AS member, bs.segment_status
       FROM booking_segment bs
       JOIN booking b ON bs.booking_id = b.booking_id
       JOIN seat_assignment sa ON sa.segment_id = bs.segment_id
       JOIN passenger p ON sa.passenger_id = p.passenger_id
       JOIN seat st ON sa.seat_id = st.seat_id
       WHERE bs.schedule_id = %s AND bs.segment_status <> 'CANCELLED'
       ORDER BY st.seat_number""",
    (int(row.schedule_id),),
)

if manifest.empty:
    st.caption("좌석이 배정된 탑승객이 없습니다.")
    st.stop()

editable = row.flight_status in ("SCHEDULED", "DELAYED")
table = pd.DataFrame({
    "id": manifest.seat_assign_id,
    "예약번호": manifest.booking_pnr,
    "탑승객": manifest.name,
    "좌석": manifest.seat_number,
    "회원": manifest.member,
    "체크인": manifest.checked,
    "탑승": manifest.is_boarded,
})
edited = st.data_editor(
    table, hide_index=True, width="stretch", key=f"mf_{row.schedule_id}",
    column_config={"id": None},
    disabled=[c for c in table.columns if c != "탑승"] if editable else True,
)
st.caption("체크인한 승객만 탑승 처리됩니다. 운항 완료 시 탑승한 회원에게 마일리지가 적립됩니다.")

c1, c2, _ = st.columns([1, 1.6, 2.4])
if editable:
    if c1.button("탑승 상태 저장", width="stretch"):
        changes = {int(i): bool(b) for i, b, old in zip(edited.id, edited.탑승, table.탑승) if b != old}
        services.set_boarded(changes)
        skipped = [n for n, b, ch in zip(edited.탑승객, edited.탑승, edited.체크인) if b and not ch]
        msg = f"탑승 상태 {len(changes)}건을 저장했습니다."
        if skipped:
            msg += f" (체크인 전이라 제외: {', '.join(skipped)})"
        S["flash_ok"] = msg
        st.rerun()
    boarded = int(manifest.is_boarded.sum())
    if c2.button(f"운항 완료 처리 · 마일리지 적립 ({boarded}명 탑승)", type="primary",
                 width="stretch", disabled=boarded == 0):
        try:
            earned = services.complete_schedule(int(row.schedule_id))
        except Exception:
            st.error("운항 완료 처리 중 문제가 생겼습니다.")
        else:
            S["flash_ok"] = "운항 완료 처리했습니다. " + (
                "적립: " + ", ".join(earned) if earned else "적립 대상 회원이 없습니다.")
            st.rerun()
else:
    st.caption(f"이 편은 '{ui.FLIGHT_KO.get(row.flight_status)}' 상태라 탑승 정보를 바꿀 수 없습니다.")
