"""
예약하기 — 탑승객 입력, 좌석 선택, 결제

담당: 예약·결제 도메인
핵심: 예약 생성부터 결제·마일리지 차감까지 하나의 트랜잭션으로 묶는다.
"""
import datetime as dt

import streamlit as st

import db

st.set_page_config(page_title="예약하기", page_icon="🎫", layout="wide")

me = db.sidebar_auth()
st.title("예약하기")

picked = st.session_state.get("picked")
if not picked:
    st.info("먼저 **항공편 검색**에서 운임을 선택하세요.")
    st.stop()

st.success(
    f"{picked['flight_number']} · {picked['flight_date']} · "
    f"{picked['dep']} → {picked['arr']} · "
    f"{picked['fare_code']} 운임 {db.won(picked['base_price'])}"
)

# 1. 예약자 -------------------------------------------------------------
# 로그인 여부가 회원 예약과 비회원 예약을 가른다.
st.subheader("1. 예약자")

if me:
    booker_id = me["member_id"]
    c1, c2 = st.columns([1, 2])
    c1.success(f"{me['member_name']} 님으로 예약합니다")
    contact = c2.text_input("연락 이메일", me["email"])
else:
    booker_id = None
    c1, c2 = st.columns([1, 2])
    c1.info("비회원 예약")
    contact = c2.text_input("연락 이메일", "guest@example.com")
    st.caption(
        "로그인하지 않으면 비회원 예약이 됩니다. "
        "회원 계정으로 조회할 수 없으므로 예약번호와 탑승객 영문 성으로 조회합니다."
    )

# 2. 탑승객 -------------------------------------------------------------
st.subheader("2. 탑승객")
st.caption("여권 영문 표기 그대로 입력합니다. 성과 이름을 바꿔 쓰면 탑승이 거부됩니다.")

pax_n = st.number_input("탑승객 수", 1, 6, picked["pax"])
passengers = []
for i in range(int(pax_n)):
    c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 2])
    last = c1.text_input("성 (여권)", key=f"ln{i}", placeholder="HONG")
    first = c2.text_input("이름 (여권)", key=f"fn{i}", placeholder="GILDONG")
    birth = c3.date_input(
        "생년월일", dt.date(2000, 1, 1),
        min_value=dt.date(1920, 1, 1), max_value=dt.date.today(), key=f"bd{i}"
    )
    ptype = c4.selectbox("승객 유형", ["ADULT", "CHILD", "INFANT"], key=f"pt{i}")

    # 로그인한 회원 본인이 타는 경우에만 회원을 연결한다.
    # 이 값이 NULL이면 마일리지 적립 대상에서 빠진다.
    if me:
        is_self = c5.checkbox(f"{me['member_name']} 본인", key=f"mk{i}", value=(i == 0))
        link_id = me["member_id"] if is_self else None
    else:
        c5.text_input("회원 연결", "없음 (비회원)", disabled=True, key=f"mk{i}")
        link_id = None

    passengers.append(
        {"last": last.strip().upper(), "first": first.strip().upper(),
         "birth": birth, "type": ptype, "member_id": link_id}
    )

st.caption(
    "회원 본인으로 체크한 탑승객만 마일리지 적립 대상입니다. "
    "동반 승객이나 비회원은 적립되지 않습니다."
)

# 3. 좌석 ---------------------------------------------------------------
st.subheader("3. 좌석 선택")

FREE_SEATS = """
SELECT s.seat_id, s.seat_number, s.seat_class
FROM seat s
JOIN flight_schedule fs ON fs.aircraft_id = s.aircraft_id
WHERE fs.schedule_id = %s
  AND s.seat_class   = %s
  AND s.seat_id NOT IN (
      SELECT sa.seat_id
      FROM seat_assignment sa
      JOIN booking_segment bs ON sa.segment_id = bs.segment_id
      WHERE bs.schedule_id = %s AND bs.segment_status <> 'CANCELLED'
  )
ORDER BY s.seat_number
"""
free = db.q(FREE_SEATS, (picked["schedule_id"], picked["seat_class"], picked["schedule_id"]))

chosen = []
if free.empty:
    st.warning("배정 가능한 좌석이 없습니다.")
else:
    seat_map = {r.seat_number: int(r.seat_id) for r in free.itertuples()}
    cols = st.columns(min(int(pax_n), 4))
    used = set()
    for i in range(int(pax_n)):
        label = f"{passengers[i]['last'] or '승객'} {passengers[i]['first']}".strip()
        avail = [s for s in seat_map if s not in used]
        if passengers[i]["type"] == "INFANT":
            cols[i % len(cols)].text_input(
                f"{label} 좌석", "좌석 없음 (보호자 동반)", disabled=True, key=f"st{i}"
            )
            chosen.append(None)
            continue
        pick = cols[i % len(cols)].selectbox(f"{label} 좌석", avail, key=f"st{i}")
        used.add(pick)
        chosen.append(seat_map[pick])

st.caption(
    "유아는 좌석을 배정하지 않습니다. "
    "이미 배정된 좌석은 목록에서 빠지고, 동시 요청은 "
    "`UNIQUE(segment_id, seat_id)` 제약이 DB에서 막습니다."
)

# 4. 결제 ---------------------------------------------------------------
st.subheader("4. 결제")

billable = sum(1 for p in passengers if p["type"] != "INFANT")
infant_n = sum(1 for p in passengers if p["type"] == "INFANT")
total = picked["base_price"] * billable + int(picked["base_price"] * 0.1) * infant_n

c1, c2 = st.columns([1, 2])
c1.metric("총 결제 금액", db.won(total))
c1.caption(f"성인·소아 {billable}명 + 유아 {infant_n}명(10%)")

use_mile = 0
balance = 0
if booker_id:
    balance = db.q1(
        "SELECT current_balance FROM mileage_account WHERE member_id = %s", (booker_id,)
    ) or 0
    c2.write(f"보유 마일리지 **{balance:,}** 마일 (1마일 = 10원)")
    max_mile = min(balance, total // 10)
    use_mile = c2.number_input(
        "사용할 마일리지", 0, int(max_mile), 0, step=100,
        help="나머지는 카드로 결제됩니다",
    )
    c2.caption(f"마일리지 {use_mile * 10:,}원 + 카드 {total - use_mile * 10:,}원")
else:
    c2.info("비회원은 마일리지 계좌가 없어 카드 결제만 가능합니다.")

# 5. 확정 ---------------------------------------------------------------
st.divider()

incomplete = any(not p["last"] or not p["first"] for p in passengers)
if incomplete:
    st.warning("탑승객 영문 성·이름을 모두 입력하세요.")

if st.button("예약 확정", type="primary", disabled=incomplete, use_container_width=True):
    pnr = db.new_pnr()
    try:
        with db.tx() as cur:
            # 예약
            cur.execute(
                """INSERT INTO booking
                     (member_id, booking_pnr, total_price, booking_status, contact_email)
                   VALUES (%s, %s, %s, 'PENDING', %s)
                   RETURNING booking_id""",
                (booker_id, pnr, total, contact),
            )
            booking_id = cur.fetchone()[0]

            # 탑승객
            pax_ids = []
            for p in passengers:
                cur.execute(
                    """INSERT INTO passenger
                         (booking_id, member_id, last_name, first_name,
                          birth_date, passenger_type)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       RETURNING passenger_id""",
                    (booking_id, p["member_id"], p["last"], p["first"],
                     p["birth"], p["type"]),
                )
                pax_ids.append(cur.fetchone()[0])

            # 여정 구간 (초안은 편도 1구간)
            cur.execute(
                """INSERT INTO booking_segment
                     (booking_id, schedule_id, fare_id, segment_order, segment_status)
                   VALUES (%s, %s, %s, 1, 'ACTIVE')
                   RETURNING segment_id""",
                (booking_id, picked["schedule_id"], picked["fare_id"]),
            )
            segment_id = cur.fetchone()[0]

            # 좌석 배정
            for pid, sid in zip(pax_ids, chosen):
                if sid is None:
                    continue
                cur.execute(
                    """INSERT INTO seat_assignment (segment_id, passenger_id, seat_id)
                       VALUES (%s, %s, %s)""",
                    (segment_id, pid, sid),
                )

            # 판매 좌석 증가 — CHECK 제약이 초과 판매를 막는다
            cur.execute(
                "UPDATE fare SET seats_sold = seats_sold + %s WHERE fare_id = %s",
                (billable, picked["fare_id"]),
            )

            # 결제: 마일리지 먼저, 나머지는 카드
            if use_mile > 0:
                cur.execute(
                    """INSERT INTO payment (booking_id, payment_method, amount, payment_status)
                       VALUES (%s, 'MILEAGE', %s, 'COMPLETED')
                       RETURNING payment_id""",
                    (booking_id, use_mile * 10),
                )
                pay_id = cur.fetchone()[0]

                cur.execute(
                    "SELECT mileage_id FROM mileage_account WHERE member_id = %s",
                    (booker_id,),
                )
                mileage_id = cur.fetchone()[0]

                cur.execute(
                    """INSERT INTO mileage_history
                         (mileage_id, payment_id, change_type, amount, reason)
                       VALUES (%s, %s, 'USE', %s, %s)""",
                    (mileage_id, pay_id, use_mile, f"예약 {pnr} 결제 사용"),
                )

                # 선입선출: 만료일이 빠른 적립 건부터 차감
                remain = use_mile
                cur.execute(
                    """SELECT history_id, remaining_amount
                       FROM mileage_history
                       WHERE mileage_id = %s AND change_type = 'EARN'
                         AND remaining_amount > 0
                       ORDER BY expire_at
                       FOR UPDATE""",
                    (mileage_id,),
                )
                for hid, left in cur.fetchall():
                    if remain <= 0:
                        break
                    take = min(left, remain)
                    cur.execute(
                        """UPDATE mileage_history
                           SET remaining_amount = remaining_amount - %s
                           WHERE history_id = %s""",
                        (take, hid),
                    )
                    remain -= take

                cur.execute(
                    """UPDATE mileage_account
                       SET current_balance = current_balance - %s,
                           last_updated_at = NOW()
                       WHERE mileage_id = %s""",
                    (use_mile, mileage_id),
                )

            card = total - use_mile * 10
            if card > 0:
                cur.execute(
                    """INSERT INTO payment
                         (booking_id, payment_method, amount, payment_status, approval_no)
                       VALUES (%s, 'CARD', %s, 'COMPLETED', %s)""",
                    (booking_id, card, f"A{pnr}"),
                )

            # 결제 완료 → 발권
            cur.execute(
                "UPDATE booking SET booking_status = 'TICKETED' WHERE booking_id = %s",
                (booking_id,),
            )

    except Exception as e:
        st.error("예약에 실패했습니다. 전체가 롤백되어 아무것도 저장되지 않았습니다.")
        st.code(str(e))
        st.stop()

    st.success(f"예약이 완료되었습니다. 예약번호 **{pnr}**")
    st.balloons()
    st.session_state.pop("picked", None)
    st.info("**예약 조회** 페이지에서 예약번호로 확인할 수 있습니다.")
