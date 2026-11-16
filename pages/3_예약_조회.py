"""
예약 조회 — 여정·좌석·결제 확인, 구간 단위 취소

담당: 예약 도메인
핵심: 구간마다 상태가 있어 왕복 중 한 편만 취소할 수 있다.
"""
import streamlit as st

import db

st.set_page_config(page_title="예약 조회", page_icon="📋", layout="wide")

me = db.sidebar_auth()
st.title("예약 조회 · 취소")

tab_pnr, tab_member = st.tabs(["예약번호로 조회", "회원 계정으로 조회"])

with tab_pnr:
    c1, c2 = st.columns([1, 2])
    pnr = c1.text_input("예약번호 (PNR)", placeholder="K7X2MQ", max_chars=6).upper()
    last = c2.text_input("탑승객 영문 성", placeholder="HONG").upper()
    st.caption(
        "비회원 예약은 계정에 연결되어 있지 않아, 예약번호와 탑승객 성으로 조회합니다."
    )
    if pnr and last:
        found = db.q1(
            """SELECT b.booking_id
               FROM booking b
               JOIN passenger p ON b.booking_id = p.booking_id
               WHERE b.booking_pnr = %s AND p.last_name = %s
               LIMIT 1""",
            (pnr, last),
        )
        st.session_state["view_booking"] = found
        if not found:
            st.warning("일치하는 예약이 없습니다.")

with tab_member:
    if not me:
        st.info("회원 계정으로 조회하려면 왼쪽 사이드바에서 로그인하세요.")
        st.caption(
            "비회원 예약은 `BOOKING.member_id` 가 NULL이라 계정으로 찾을 수 없습니다. "
            "예약번호 탭을 이용하세요."
        )
        mine = None
    else:
        st.caption(f"{me['member_name']} 님의 예약 내역")
        mine = db.q(
            """SELECT booking_id, booking_pnr, booking_date::date AS 예약일,
                      total_price, booking_status
               FROM booking WHERE member_id = %s ORDER BY booking_date DESC""",
            (me["member_id"],),
        )
    if mine is None:
        pass
    elif mine.empty:
        st.info("예약 내역이 없습니다.")
    else:
        for r in mine.itertuples():
            cols = st.columns([2, 2, 2, 2, 1])
            cols[0].write(f"**{r.booking_pnr}**")
            cols[1].write(str(r.예약일))
            cols[2].write(db.won(r.total_price))
            cols[3].write(r.booking_status)
            if cols[4].button("열기", key=f"open{r.booking_id}"):
                st.session_state["view_booking"] = int(r.booking_id)

booking_id = st.session_state.get("view_booking")
if not booking_id:
    st.stop()

st.divider()

# 예약 요약 -------------------------------------------------------------
head = db.q(
    """SELECT b.booking_pnr, b.booking_date, b.total_price, b.booking_status,
              b.contact_email, m.member_name
       FROM booking b
       LEFT JOIN member m ON b.member_id = m.member_id
       WHERE b.booking_id = %s""",
    (booking_id,),
).iloc[0]

c = st.columns(5)
c[0].metric("예약번호", head.booking_pnr)
c[1].metric("예약자", head.member_name or "비회원")
c[2].metric("결제 금액", db.won(head.total_price))
c[3].metric("상태", head.booking_status)
c[4].metric("연락처", head.contact_email)

# 여정 구간 -------------------------------------------------------------
st.subheader("여정")

SEGMENTS = """
SELECT bs.segment_id, bs.segment_order, bs.segment_status,
       f.flight_number, fs.flight_date, fs.flight_status,
       fs.terminal, fs.gate,
       f.std_dep_time,
       r.dep_airport_code, r.arr_airport_code, r.distance_km,
       fa.fare_code, fa.seat_class, fa.base_price, fa.cancellation_fee
FROM booking_segment bs
JOIN flight_schedule fs ON bs.schedule_id = fs.schedule_id
JOIN flight f           ON fs.flight_number = f.flight_number
JOIN route  r           ON f.route_id = r.route_id
JOIN fare   fa          ON bs.fare_id = fa.fare_id
WHERE bs.booking_id = %s
ORDER BY bs.segment_order
"""
segs = db.q(SEGMENTS, (booking_id,))

SEG_KO = {"ACTIVE": "유효", "CANCELLED": "취소됨", "FLOWN": "탑승완료"}

for s in segs.itertuples():
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([1, 4, 2, 2])
        c1.markdown(f"**{s.segment_order}구간**")
        c2.markdown(
            f"**{s.flight_number}** {s.dep_airport_code} → {s.arr_airport_code}"
        )
        gate = f" · 탑승구 {s.gate}" if s.gate else ""
        c2.caption(
            f"{s.flight_date} {str(s.std_dep_time)[:5]} · "
            f"{s.fare_code} 운임{gate}"
        )
        c3.write(SEG_KO.get(s.segment_status, s.segment_status))

        # 좌석
        seats = db.q(
            """SELECT p.last_name, p.first_name, p.passenger_type,
                      st.seat_number, sa.is_boarded
               FROM seat_assignment sa
               JOIN passenger p ON sa.passenger_id = p.passenger_id
               JOIN seat st     ON sa.seat_id = st.seat_id
               WHERE sa.segment_id = %s
               ORDER BY st.seat_number""",
            (s.segment_id,),
        )
        if not seats.empty:
            c2.caption(
                "좌석 " + ", ".join(
                    f"{r.seat_number}({r.last_name})" for r in seats.itertuples()
                )
            )

        if s.segment_status == "ACTIVE":
            refund = max(0, s.base_price - s.cancellation_fee)
            if c4.button(
                f"구간 취소", key=f"cancel{s.segment_id}", use_container_width=True
            ):
                try:
                    with db.tx() as cur:
                        # 구간만 취소
                        cur.execute(
                            """UPDATE booking_segment SET segment_status = 'CANCELLED'
                               WHERE segment_id = %s""",
                            (s.segment_id,),
                        )
                        # 좌석 해제
                        cur.execute(
                            "DELETE FROM seat_assignment WHERE segment_id = %s",
                            (s.segment_id,),
                        )
                        # 판매 좌석 되돌리기
                        cur.execute(
                            """UPDATE fare SET seats_sold = GREATEST(seats_sold - %s, 0)
                               WHERE fare_id = (SELECT fare_id FROM booking_segment
                                                WHERE segment_id = %s)""",
                            (len(seats), s.segment_id),
                        )
                        # 환불 기록
                        cur.execute(
                            """UPDATE payment
                               SET refund_amount = refund_amount + %s,
                                   payment_status = 'REFUNDED'
                               WHERE payment_id = (
                                   SELECT payment_id FROM payment
                                   WHERE booking_id = %s AND payment_method = 'CARD'
                                     AND payment_status = 'COMPLETED'
                                   ORDER BY payment_id LIMIT 1)""",
                            (refund, booking_id),
                        )
                        # 모든 구간이 취소되면 예약 전체도 취소
                        cur.execute(
                            """UPDATE booking SET booking_status = 'CANCELLED'
                               WHERE booking_id = %s
                                 AND NOT EXISTS (
                                     SELECT 1 FROM booking_segment
                                     WHERE booking_id = %s
                                       AND segment_status <> 'CANCELLED')""",
                            (booking_id, booking_id),
                        )
                except Exception as e:
                    st.error("취소 처리에 실패했습니다.")
                    st.code(str(e))
                else:
                    st.success(f"{s.segment_order}구간이 취소되었습니다. 환불 {db.won(refund)}")
                    st.rerun()
            c4.caption(f"수수료 {db.won(s.cancellation_fee)}")

# 결제 내역 -------------------------------------------------------------
st.subheader("결제 내역")
pays = db.q(
    """SELECT payment_id AS 결제번호, payment_method AS 수단, amount AS 금액,
              payment_status AS 상태, approval_no AS 승인번호,
              refund_amount AS 환불, payment_date AS 일시
       FROM payment WHERE booking_id = %s ORDER BY payment_id""",
    (booking_id,),
)
st.dataframe(pays, use_container_width=True, hide_index=True)

done = db.q1(
    """SELECT COALESCE(SUM(amount), 0) FROM payment
       WHERE booking_id = %s AND payment_status = 'COMPLETED'""",
    (booking_id,),
)
if done == head.total_price:
    st.caption(f"완료 결제 합계 {db.won(done)} = 예약 총액 {db.won(head.total_price)} · 일치")
else:
    st.caption(f"완료 결제 합계 {db.won(done)} / 예약 총액 {db.won(head.total_price)}")
