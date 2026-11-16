"""
체크인 · 탑승 — 탑승권 발급, 탑승 처리, 마일리지 적립

담당: 좌석·탑승 도메인
핵심: 적립 조건 세 가지(회원 연결 · 실제 탑승 · 구간 완료)를 모두 만족해야 쌓인다.
"""
import streamlit as st

import db

st.set_page_config(page_title="체크인", page_icon="🛂", layout="wide")

me = db.sidebar_auth()
st.title("체크인 · 탑승")

pnr = st.text_input("예약번호 (PNR)", placeholder="K7X2MQ", max_chars=6).upper()
if not pnr:
    st.info("예약번호를 입력하세요.")
    st.stop()

PAX = """
SELECT sa.seat_assign_id, sa.checked_in_at, sa.is_boarded,
       p.passenger_id, p.last_name, p.first_name, p.passport_no,
       p.passenger_type, p.member_id,
       st.seat_number, st.seat_class,
       bs.segment_id, bs.segment_order, bs.segment_status,
       f.flight_number, fs.flight_date, fs.flight_status,
       fs.terminal, fs.gate, f.std_dep_time,
       r.dep_airport_code, r.arr_airport_code, r.distance_km,
       fa.mileage_rate
FROM booking b
JOIN booking_segment bs  ON b.booking_id = bs.booking_id
JOIN seat_assignment sa  ON bs.segment_id = sa.segment_id
JOIN passenger p         ON sa.passenger_id = p.passenger_id
JOIN seat st             ON sa.seat_id = st.seat_id
JOIN flight_schedule fs  ON bs.schedule_id = fs.schedule_id
JOIN flight f            ON fs.flight_number = f.flight_number
JOIN route r             ON f.route_id = r.route_id
JOIN fare fa             ON bs.fare_id = fa.fare_id
WHERE b.booking_pnr = %s
  AND bs.segment_status <> 'CANCELLED'
ORDER BY bs.segment_order, st.seat_number
"""
rows = db.q(PAX, (pnr,))

if rows.empty:
    st.warning("해당 예약의 좌석 배정 내역이 없습니다.")
    st.stop()

for order, g in rows.groupby("segment_order"):
    head = g.iloc[0]
    st.subheader(
        f"{order}구간 · {head.flight_number} "
        f"{head.dep_airport_code} → {head.arr_airport_code} · {head.flight_date}"
    )

    for r in g.itertuples():
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
            c1.markdown(f"**{r.last_name} / {r.first_name}**")
            c1.caption(
                f"{r.passenger_type} · 여권 {r.passport_no or '미입력'} · "
                + ("회원 연결됨" if r.member_id else "비회원")
            )
            c2.write(f"좌석 **{r.seat_number}**")
            c2.caption(r.seat_class)

            if r.checked_in_at:
                c3.write(":green[체크인 완료]")
                c3.caption(str(r.checked_in_at)[:16])
            else:
                c3.write("체크인 전")

            if r.is_boarded:
                c4.write(":green[탑승]")
            elif r.checked_in_at:
                if c4.button("탑승 처리", key=f"brd{r.seat_assign_id}",
                             use_container_width=True):
                    db.execute(
                        "UPDATE seat_assignment SET is_boarded = TRUE WHERE seat_assign_id = %s",
                        (r.seat_assign_id,),
                    )
                    st.rerun()
            else:
                if c4.button("체크인", key=f"chk{r.seat_assign_id}",
                             use_container_width=True):
                    db.execute(
                        """UPDATE seat_assignment SET checked_in_at = NOW()
                           WHERE seat_assign_id = %s""",
                        (r.seat_assign_id,),
                    )
                    st.rerun()

            if r.checked_in_at:
                with c1.expander("탑승권"):
                    st.code(
                        f"""{r.last_name} / {r.first_name}
{r.flight_number}   {r.flight_date}
{r.dep_airport_code} → {r.arr_airport_code}   {str(r.std_dep_time)[:5]}
터미널 {r.terminal or '-'}   탑승구 {r.gate or '미정'}
좌석 {r.seat_number}   {r.seat_class}
예약번호 {pnr}""",
                        language=None,
                    )

    # 운항 완료 처리 ----------------------------------------------------
    boarded = int(g["is_boarded"].sum())
    seg_id = int(head.segment_id)

    if head.segment_status == "FLOWN":
        st.caption("이 구간은 탑승 완료 처리되었습니다.")
    elif boarded > 0:
        if st.button(
            f"{order}구간 운항 완료 처리 · 마일리지 적립", key=f"fly{seg_id}",
            type="primary",
        ):
            earned = []
            try:
                with db.tx() as cur:
                    cur.execute(
                        """UPDATE booking_segment SET segment_status = 'FLOWN'
                           WHERE segment_id = %s""",
                        (seg_id,),
                    )
                    # 적립 조건 세 가지를 모두 만족하는 승객만
                    cur.execute(
                        """SELECT p.passenger_id, p.last_name, p.first_name,
                                  ma.mileage_id,
                                  (r.distance_km * fa.mileage_rate / 100)::int AS miles
                           FROM seat_assignment sa
                           JOIN passenger p        ON sa.passenger_id = p.passenger_id
                           JOIN mileage_account ma ON p.member_id = ma.member_id
                           JOIN booking_segment bs ON sa.segment_id = bs.segment_id
                           JOIN fare fa            ON bs.fare_id = fa.fare_id
                           JOIN flight_schedule fs ON bs.schedule_id = fs.schedule_id
                           JOIN flight f           ON fs.flight_number = f.flight_number
                           JOIN route r            ON f.route_id = r.route_id
                           WHERE sa.segment_id = %s
                             AND p.member_id IS NOT NULL
                             AND sa.is_boarded = TRUE""",
                        (seg_id,),
                    )
                    for pid, ln, fn, mid, miles in cur.fetchall():
                        cur.execute(
                            """INSERT INTO mileage_history
                                 (mileage_id, segment_id, change_type, amount,
                                  remaining_amount, expire_at, reason)
                               VALUES (%s, %s, 'EARN', %s, %s,
                                       CURRENT_DATE + INTERVAL '10 years', %s)""",
                            (mid, seg_id, miles, miles,
                             f"{head.flight_number} 탑승 적립"),
                        )
                        cur.execute(
                            """UPDATE mileage_account
                               SET current_balance = current_balance + %s,
                                   last_updated_at = NOW()
                               WHERE mileage_id = %s""",
                            (miles, mid),
                        )
                        earned.append(f"{ln}/{fn} +{miles:,}마일")
            except Exception as e:
                st.error("처리에 실패했습니다.")
                st.code(str(e))
            else:
                if earned:
                    st.success("적립 완료 · " + ", ".join(earned))
                else:
                    st.info("적립 대상 승객이 없습니다. 회원으로 연결된 탑승객만 적립됩니다.")
                st.rerun()
    else:
        st.caption("탑승 처리된 승객이 있어야 운항 완료로 넘길 수 있습니다.")
