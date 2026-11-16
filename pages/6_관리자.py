"""
관리자 — 운항 상태 관리, 노선별 탑승률·매출 통계

담당: 기준정보·운항 도메인
핵심: 집계 쿼리로 설계가 실제 질문에 답할 수 있는지 보여준다.
"""
import datetime as dt

import streamlit as st

import db

st.set_page_config(page_title="관리자", page_icon="⚙", layout="wide")

me = db.sidebar_auth()
st.title("관리자")

tab1, tab2, tab3 = st.tabs(["운항 관리", "탑승률·매출", "제약조건 검증"])

# ------------------------------------------------------------------ 운항
with tab1:
    st.subheader("운항 상태 변경")
    date = st.date_input("운항일", dt.date.today())

    sched = db.q(
        """SELECT fs.schedule_id, f.flight_number,
                  r.dep_airport_code || ' → ' || r.arr_airport_code AS 구간,
                  f.std_dep_time AS 출발, ac.model_name AS 기종,
                  fs.flight_status AS 상태, fs.terminal AS 터미널, fs.gate AS 탑승구,
                  (SELECT COALESCE(SUM(fa.seats_sold), 0) FROM fare fa
                   WHERE fa.schedule_id = fs.schedule_id) AS 판매석
           FROM flight_schedule fs
           JOIN flight f   ON fs.flight_number = f.flight_number
           JOIN route r    ON f.route_id = r.route_id
           JOIN aircraft ac ON fs.aircraft_id = ac.aircraft_id
           WHERE fs.flight_date = %s
           ORDER BY f.std_dep_time""",
        (date,),
    )

    if sched.empty:
        st.info("해당 날짜의 운항 스케줄이 없습니다.")
    else:
        st.dataframe(sched.drop(columns=["schedule_id"]),
                     use_container_width=True, hide_index=True)

        st.write("")
        c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
        target = c1.selectbox(
            "변경할 운항편",
            sched.schedule_id.tolist(),
            format_func=lambda i: (
                f"{sched[sched.schedule_id == i].iloc[0].flight_number} "
                f"{sched[sched.schedule_id == i].iloc[0].구간}"
            ),
        )
        new_status = c2.selectbox(
            "상태", ["SCHEDULED", "DELAYED", "CANCELLED", "COMPLETED"]
        )
        terminal = c3.text_input("터미널", "T1")
        gate = c4.text_input("탑승구", "")

        if st.button("적용", type="primary"):
            db.execute(
                """UPDATE flight_schedule
                   SET flight_status = %s, terminal = %s, gate = NULLIF(%s, '')
                   WHERE schedule_id = %s""",
                (new_status, terminal or None, gate, int(target)),
            )
            st.success("변경되었습니다.")
            st.rerun()

        if new_status == "CANCELLED":
            affected = db.q(
                """SELECT b.booking_pnr AS 예약번호, b.contact_email AS 연락처,
                          count(*) AS 승객수
                   FROM booking_segment bs
                   JOIN booking b ON bs.booking_id = b.booking_id
                   LEFT JOIN seat_assignment sa ON bs.segment_id = sa.segment_id
                   WHERE bs.schedule_id = %s AND bs.segment_status = 'ACTIVE'
                   GROUP BY b.booking_pnr, b.contact_email""",
                (int(target),),
            )
            if not affected.empty:
                st.warning(f"결항 시 영향받는 예약 {len(affected)}건")
                st.dataframe(affected, use_container_width=True, hide_index=True)
                st.caption(
                    "구간 단위로 관리하므로 영향받는 예약만 정확히 추출할 수 있습니다."
                )

# ------------------------------------------------------------------ 통계
with tab2:
    st.subheader("노선별 탑승률 · 매출")
    c1, c2 = st.columns(2)
    d1 = c1.date_input("시작일", dt.date.today() - dt.timedelta(days=10))
    d2 = c2.date_input("종료일", dt.date.today() + dt.timedelta(days=10))

    STATS = """
    SELECT r.dep_airport_code || ' → ' || r.arr_airport_code AS 노선,
           count(DISTINCT fs.schedule_id)        AS 운항편수,
           SUM(fa.seats_allotted)                AS 공급석,
           SUM(fa.seats_sold)                    AS 판매석,
           ROUND(100.0 * SUM(fa.seats_sold) / NULLIF(SUM(fa.seats_allotted), 0), 1) AS "탑승률(%%)",
           SUM(fa.seats_sold * fa.base_price)    AS 매출
    FROM flight_schedule fs
    JOIN flight f ON fs.flight_number = f.flight_number
    JOIN route  r ON f.route_id = r.route_id
    JOIN fare  fa ON fa.schedule_id = fs.schedule_id
    WHERE fs.flight_date BETWEEN %s AND %s
      AND fs.flight_status <> 'CANCELLED'
    GROUP BY r.dep_airport_code, r.arr_airport_code
    ORDER BY 매출 DESC
    """
    stats = db.q(STATS, (d1, d2))

    if stats.empty:
        st.info("해당 기간 데이터가 없습니다.")
    else:
        st.dataframe(stats, use_container_width=True, hide_index=True)
        st.bar_chart(stats.set_index("노선")["탑승률(%)"], height=260)

        st.subheader("운임 등급별 판매 비중")
        byfare = db.q(
            """SELECT fa.seat_class AS 좌석등급, fa.fare_code AS 운임코드,
                      SUM(fa.seats_sold) AS 판매석,
                      SUM(fa.seats_allotted) AS 배정석,
                      ROUND(100.0 * SUM(fa.seats_sold)
                            / NULLIF(SUM(fa.seats_allotted), 0), 1) AS "소진율(%%)",
                      SUM(fa.seats_sold * fa.base_price) AS 매출
               FROM fare fa
               JOIN flight_schedule fs ON fa.schedule_id = fs.schedule_id
               WHERE fs.flight_date BETWEEN %s AND %s
               GROUP BY fa.seat_class, fa.fare_code
               ORDER BY 매출 DESC""",
            (d1, d2),
        )
        st.dataframe(byfare, use_container_width=True, hide_index=True)
        st.caption(
            "특가(Q) 운임의 소진율이 높고 정규(Y)가 낮은 것이 정상입니다. "
            "좌석이 남아 있어도 특가가 매진되는 상황이 여기서 드러납니다."
        )

        st.subheader("소멸 예정 마일리지")
        exp = db.q(
            """SELECT m.member_name AS 회원, ma.tier AS 등급,
                      ma.current_balance AS 잔액,
                      COALESCE(SUM(h.remaining_amount), 0) AS "1년내 소멸예정"
               FROM mileage_account ma
               JOIN member m ON ma.member_id = m.member_id
               LEFT JOIN mileage_history h
                      ON h.mileage_id = ma.mileage_id
                     AND h.change_type = 'EARN'
                     AND h.remaining_amount > 0
                     AND h.expire_at <= CURRENT_DATE + INTERVAL '1 year'
               GROUP BY m.member_name, ma.tier, ma.current_balance
               ORDER BY "1년내 소멸예정" DESC"""
        )
        st.dataframe(exp, use_container_width=True, hide_index=True)

# ------------------------------------------------------------------ 검증
with tab3:
    st.subheader("제약조건이 실제로 막는지 확인")
    st.caption(
        "설계 문서의 주장이 DB에서 실제로 동작하는지 보여주는 화면입니다. "
        "모두 실패해야 정상입니다."
    )

    tests = [
        (
            "같은 구간에 같은 좌석 중복 배정",
            "UNIQUE(segment_id, seat_id)",
            """INSERT INTO seat_assignment (segment_id, passenger_id, seat_id)
               SELECT segment_id, passenger_id, seat_id FROM seat_assignment LIMIT 1""",
        ),
        (
            "배정 좌석보다 많이 판매",
            "CHECK(seats_sold <= seats_allotted)",
            "UPDATE fare SET seats_sold = seats_allotted + 1 WHERE fare_id = (SELECT MIN(fare_id) FROM fare)",
        ),
        (
            "같은 편명을 같은 날짜에 두 번 등록",
            "UNIQUE(flight_number, flight_date)",
            """INSERT INTO flight_schedule (flight_number, aircraft_id, flight_date)
               SELECT flight_number, aircraft_id, flight_date FROM flight_schedule LIMIT 1""",
        ),
        (
            "출발지와 도착지가 같은 노선",
            "CHECK(dep <> arr)",
            """INSERT INTO route (dep_airport_code, arr_airport_code, distance_km, flight_duration)
               VALUES ('ICN', 'ICN', 100, 60)""",
        ),
        (
            "적립(EARN) 행에 결제를 연결",
            "CHECK(ck_mh_source)",
            """INSERT INTO mileage_history
                 (mileage_id, payment_id, change_type, amount, remaining_amount, expire_at)
               VALUES (1, (SELECT MIN(payment_id) FROM payment), 'EARN', 100, 100, CURRENT_DATE)""",
        ),
    ]

    if st.button("검증 실행"):
        for name, rule, sql in tests:
            with db.get_conn() as conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute(sql)
                    conn.rollback()  # 성공했더라도 되돌린다
                    st.error(f"**{name}** — 막히지 않음 (`{rule}` 확인 필요)")
                except Exception as e:
                    conn.rollback()
                    msg = str(e).split("\n")[0]
                    st.success(f"**{name}** — 차단됨")
                    st.caption(f"`{rule}` · {msg}")
