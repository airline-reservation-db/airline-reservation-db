"""온라인 체크인 — 예약 확인 → 좌석 확인 → 탑승권"""
import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import db
import services
import ui

S = st.session_state
NOW = dt.datetime.now(ZoneInfo("Asia/Seoul")).replace(tzinfo=None)
S.setdefault("ci_step", 0)

PAX_SQL = """
SELECT sa.seat_assign_id, sa.checked_in_at, sa.is_boarded,
       p.last_name, p.first_name, p.passenger_type,
       st.seat_number, st.seat_class,
       bs.segment_id, bs.segment_order,
       f.flight_number, fs.flight_date, fs.flight_status, fs.terminal, fs.gate,
       f.std_dep_time, f.std_arr_time, r.flight_duration,
       r.dep_airport_code, r.arr_airport_code, da.city AS dep_city, aa.city AS arr_city
FROM booking b
JOIN booking_segment bs  ON b.booking_id = bs.booking_id
JOIN seat_assignment sa  ON bs.segment_id = sa.segment_id
JOIN passenger p         ON sa.passenger_id = p.passenger_id
JOIN seat st             ON sa.seat_id = st.seat_id
JOIN flight_schedule fs  ON bs.schedule_id = fs.schedule_id
JOIN flight f            ON fs.flight_number = f.flight_number
JOIN route r             ON f.route_id = r.route_id
JOIN airport da          ON r.dep_airport_code = da.airport_code
JOIN airport aa          ON r.arr_airport_code = aa.airport_code
WHERE b.booking_id = %s
  AND bs.segment_status = 'ACTIVE'
  AND fs.flight_status IN ('SCHEDULED', 'DELAYED')
ORDER BY bs.segment_order, p.passenger_id
"""


def load(booking_id: int) -> pd.DataFrame:
    rows = db.q(PAX_SQL, (booking_id,))
    if rows.empty:
        return rows
    dep = pd.to_datetime(rows.flight_date.astype(str) + " " + rows.std_dep_time.astype(str))
    return rows[dep > NOW]


def reset():
    for k in ("ci_step", "ci_booking", "ci_pnr", "ci_last"):
        S.pop(k, None)


ui.html('<h1 style="text-align:center">온라인 체크인</h1>')
ui.steps(["예약 확인", "좌석 확인", "탑승권"], S["ci_step"])

_, mid, _ = st.columns([1, 2.4, 1])

# ---------------------------------------------------------------- 1. 예약 확인
if S["ci_step"] == 0 or (S["ci_step"] > 0 and "ci_booking" not in S and "ci_pnr" not in S):
    S["ci_step"] = 0
    with mid.container(border=True):
        st.subheader("예약 확인")
        st.caption("예약번호와 탑승객 영문 성을 입력하세요.")
        if "ci_msg" in S:
            st.warning(S.pop("ci_msg"))
        with st.form("ci_find", border=False):
            pnr = st.text_input("예약번호", max_chars=6, placeholder="K7X2MQ")
            last = st.text_input("탑승객 영문 성", placeholder="HONG")
            ok = st.form_submit_button("다음", type="primary", width="stretch")
        if ok:
            S["ci_pnr"], S["ci_last"] = pnr.strip().upper(), last.strip().upper()
            S["ci_step"] = 1
            st.rerun()
    st.stop()

# 예약번호 → booking_id
if "ci_booking" not in S:
    found = db.q1(
        """SELECT b.booking_id FROM booking b JOIN passenger p ON b.booking_id = p.booking_id
           WHERE b.booking_pnr = %s AND upper(p.last_name) = %s AND b.booking_status <> 'CANCELLED'
           LIMIT 1""",
        (S.get("ci_pnr", ""), S.get("ci_last", "")),
    )
    if not found:
        reset()
        S["ci_step"] = 0
        S["ci_msg"] = "일치하는 예약이 없거나 취소된 예약입니다."
        st.rerun()
    S["ci_booking"] = int(found)

rows = load(S["ci_booking"])
if rows.empty:
    with mid.container(border=True):
        st.write("체크인할 수 있는 항공편이 없습니다.")
        st.caption("이미 출발했거나, 결항·취소된 구간은 체크인할 수 없습니다.")
        if st.button("처음으로", width="stretch"):
            reset()
            st.rerun()
    st.stop()

# ---------------------------------------------------------------- 2. 좌석 확인
if S["ci_step"] == 1:
    with mid.container(border=True):
        st.subheader("좌석 확인")
        st.caption(f"예약번호 {S.get('ci_pnr', '')} · 체크인할 탑승객을 선택하세요.")
        picked = []
        for seg_id, g in rows.groupby("segment_id", sort=False):
            h = g.iloc[0]
            gate = f" · 탑승구 {h.gate}" if h.gate else ""
            st.html(
                f'<div class="sky-bar"><b>{ui.esc(h.flight_number)}</b>'
                f'<span>{ui.esc(h.dep_airport_code)} {ui.hhmm(h.std_dep_time)} → '
                f'{ui.esc(h.arr_airport_code)} {ui.hhmm(h.std_arr_time)}</span>'
                f'<span class="sky-muted">{ui.kdate(h.flight_date)}{ui.esc(gate)}</span></div>'
            )
            for r in g.itertuples():
                c1, c2, c3 = st.columns([3, 1, 1.2], vertical_alignment="center")
                done = pd.notna(r.checked_in_at)
                if done:
                    c1.write(f"{r.last_name}/{r.first_name}")
                    c3.html(ui.badge("체크인 완료", "outline"))
                else:
                    if c1.checkbox(f"{r.last_name}/{r.first_name}", value=True, key=f"ci_{r.seat_assign_id}"):
                        picked.append(int(r.seat_assign_id))
                    c3.html(ui.badge("미완료", "muted"))
                c2.write(f"**{r.seat_number}**")
        st.checkbox("위험물 반입 금지 규정을 확인했으며 위 정보가 맞습니다.", key="ci_agree")

        all_done = rows.checked_in_at.notna().all()
        c1, c2 = st.columns(2)
        if c1.button("이전", width="stretch"):
            reset()
            st.rerun()
        if all_done:
            if c2.button("탑승권 보기", type="primary", width="stretch"):
                S["ci_step"] = 2
                st.rerun()
        elif c2.button("체크인 완료하기", type="primary", width="stretch",
                       disabled=not picked or not S.get("ci_agree")):
            try:
                services.check_in(picked)
            except Exception:
                st.error("체크인 처리 중 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.")
            else:
                S["ci_step"] = 2
                st.rerun()
    st.stop()

# ---------------------------------------------------------------- 3. 탑승권
done = rows[rows.checked_in_at.notna()]
with mid.container(border=True):
    if done.empty:
        st.write("체크인한 탑승객이 없습니다.")
    else:
        labels = {
            int(r.seat_assign_id): f"{r.last_name}/{r.first_name}" + (f" · {r.flight_number}" if rows.segment_id.nunique() > 1 else "")
            for r in done.itertuples()
        }
        sel = st.segmented_control("탑승객", list(labels), format_func=labels.get, default=list(labels)[0],
                                   key="ci_pass", label_visibility="collapsed")
        r = done[done.seat_assign_id == (sel or list(labels)[0])].iloc[0]
        boarding = ui.add_minutes(r.std_dep_time, -30)
        st.html(f"""
<div class="sky-pass">
  <div class="top"><b>SKYDB</b><span>탑승권 BOARDING PASS</span></div>
  <div class="body">
    <div class="route">
      <div><div class="sky-label">출발</div><div class="code">{ui.esc(r.dep_airport_code)}</div><div class="sky-muted">{ui.esc(r.dep_city)}</div></div>
      <div style="text-align:center" class="sky-muted">→<br>{ui.duration(r.flight_duration)}</div>
      <div style="text-align:right"><div class="sky-label">도착</div><div class="code">{ui.esc(r.arr_airport_code)}</div><div class="sky-muted">{ui.esc(r.arr_city)}</div></div>
    </div>
    <div class="grid">
      <div><div class="sky-label">성명</div><b>{ui.esc(r.last_name)}/{ui.esc(r.first_name)}</b></div>
      <div><div class="sky-label">편명</div><b>{ui.esc(r.flight_number)}</b></div>
      <div><div class="sky-label">날짜</div><b>{ui.kdate(r.flight_date)}</b></div>
      <div><div class="sky-label">좌석</div><b>{ui.esc(r.seat_number)}</b></div>
      <div><div class="sky-label">탑승 시간</div><b>{boarding}</b></div>
      <div><div class="sky-label">탑승구</div><b>{ui.esc(r.gate or "미정")}</b></div>
      <div><div class="sky-label">터미널</div><b>{ui.esc(r.terminal or "-")}</b></div>
      <div><div class="sky-label">좌석 등급</div><b>{ui.CLASS_KO.get(r.seat_class)}</b></div>
    </div>
    <div class="pnr">{ui.esc(S.get("ci_pnr", ""))}</div>
  </div>
</div>""")
    st.write("")
    c1, c2 = st.columns(2)
    if c1.button("다른 예약 체크인", width="stretch"):
        reset()
        st.rerun()
    if c2.button("메인으로", type="primary", width="stretch"):
        reset()
        st.switch_page("views/search.py")
