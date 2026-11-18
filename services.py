"""
여러 테이블을 함께 바꾸는 업무 처리.

예약 생성, 취소, 체크인, 운항 완료(마일리지 적립), 마일리지 소멸처럼
중간에 끊기면 데이터가 어긋나는 작업은 모두 db.tx() 하나로 묶는다.
화면 코드는 이 함수들만 부르고 SQL을 직접 섞지 않는다.
"""
import db

MILE_WON = 10          # 1마일 = 10원
INFANT_RATE = 0.1      # 유아 운임 = 성인 운임의 10%
EARN_YEARS = 10        # 적립 마일리지 유효기간


# ---------------------------------------------------------------- 금액

def segment_price(base_price: int, billable: int, infants: int) -> int:
    """구간 하나의 금액. 성인·소아는 정가, 유아는 10%."""
    return int(base_price) * billable + int(int(base_price) * INFANT_RATE) * infants


# ---------------------------------------------------------------- 예약

def create_booking(*, booker_id, contact, passengers, segments, seats, method, use_mile):
    """
    passengers: [{last, first, birth, passport, type, member_id}]
    segments:   [{schedule_id, fare_id, base_price}]   (여정 순서대로)
    seats:      {구간 인덱스: {탑승객 인덱스: seat_id}}  (유아는 없음)
    method:     CARD / BANK / EASY_PAY
    use_mile:   사용할 마일리지 (회원만)
    돌려주는 값: (booking_id, pnr)
    """
    billable = sum(1 for p in passengers if p["type"] != "INFANT")
    infants = len(passengers) - billable
    total = sum(segment_price(s["base_price"], billable, infants) for s in segments)
    use_mile = int(use_mile or 0)
    if use_mile * MILE_WON > total:
        raise ValueError("마일리지 사용액이 결제 금액보다 큽니다.")

    pnr = db.new_pnr()
    with db.tx() as cur:
        cur.execute(
            """INSERT INTO booking (member_id, booking_pnr, total_price, booking_status, contact_email)
               VALUES (%s, %s, %s, 'PENDING', %s)
               RETURNING booking_id""",
            (booker_id, pnr, total, contact),
        )
        booking_id = cur.fetchone()[0]

        pax_ids = []
        for p in passengers:
            cur.execute(
                """INSERT INTO passenger
                     (booking_id, member_id, last_name, first_name, passport_no,
                      birth_date, passenger_type)
                   VALUES (%s, %s, %s, %s, NULLIF(%s, ''), %s, %s)
                   RETURNING passenger_id""",
                (booking_id, p["member_id"], p["last"], p["first"], p.get("passport", ""),
                 p["birth"], p["type"]),
            )
            pax_ids.append(cur.fetchone()[0])

        for order, seg in enumerate(segments, start=1):
            cur.execute(
                """INSERT INTO booking_segment
                     (booking_id, schedule_id, fare_id, segment_order, segment_status)
                   VALUES (%s, %s, %s, %s, 'ACTIVE')
                   RETURNING segment_id""",
                (booking_id, seg["schedule_id"], seg["fare_id"], order),
            )
            segment_id = cur.fetchone()[0]

            for pax_idx, seat_id in seats.get(order - 1, {}).items():
                cur.execute(
                    """INSERT INTO seat_assignment (segment_id, passenger_id, seat_id)
                       VALUES (%s, %s, %s)""",
                    (segment_id, pax_ids[pax_idx], seat_id),
                )

            # 판매 좌석 증가 — CHECK(seats_sold <= seats_allotted)가 초과 판매를 막는다
            cur.execute(
                "UPDATE fare SET seats_sold = seats_sold + %s WHERE fare_id = %s",
                (billable, seg["fare_id"]),
            )

        if use_mile > 0:
            _use_mileage(cur, booker_id, booking_id, use_mile, pnr)

        rest = total - use_mile * MILE_WON
        if rest > 0:
            approval = f"A{pnr}" if method in ("CARD", "EASY_PAY") else None
            cur.execute(
                """INSERT INTO payment (booking_id, payment_method, amount, payment_status, approval_no)
                   VALUES (%s, %s, %s, 'COMPLETED', %s)""",
                (booking_id, method, rest, approval),
            )

        cur.execute(
            "UPDATE booking SET booking_status = 'TICKETED' WHERE booking_id = %s",
            (booking_id,),
        )
    return booking_id, pnr


def _use_mileage(cur, member_id, booking_id, use_mile, pnr):
    """마일리지 결제 1건 + 사용 이력 + 선입선출 차감 + 잔액 갱신."""
    cur.execute(
        """INSERT INTO payment (booking_id, payment_method, amount, payment_status)
           VALUES (%s, 'MILEAGE', %s, 'COMPLETED')
           RETURNING payment_id""",
        (booking_id, use_mile * MILE_WON),
    )
    pay_id = cur.fetchone()[0]

    cur.execute("SELECT mileage_id FROM mileage_account WHERE member_id = %s FOR UPDATE", (member_id,))
    mileage_id = cur.fetchone()[0]

    cur.execute(
        """INSERT INTO mileage_history (mileage_id, payment_id, change_type, amount, reason)
           VALUES (%s, %s, 'USE', %s, %s)""",
        (mileage_id, pay_id, use_mile, f"예약 {pnr} 결제 사용"),
    )

    remain = use_mile
    cur.execute(
        """SELECT history_id, remaining_amount FROM mileage_history
           WHERE mileage_id = %s AND change_type = 'EARN' AND remaining_amount > 0
           ORDER BY expire_at
           FOR UPDATE""",
        (mileage_id,),
    )
    for hid, left in cur.fetchall():
        if remain <= 0:
            break
        take = min(left, remain)
        cur.execute(
            "UPDATE mileage_history SET remaining_amount = remaining_amount - %s WHERE history_id = %s",
            (take, hid),
        )
        remain -= take

    # 잔액이 모자라면 CHECK(current_balance >= 0)가 전체를 롤백시킨다
    cur.execute(
        """UPDATE mileage_account
           SET current_balance = current_balance - %s, last_updated_at = NOW()
           WHERE mileage_id = %s""",
        (use_mile, mileage_id),
    )


# ---------------------------------------------------------------- 취소

def cancel_quote(booking_id: int, segment_ids: list[int]) -> dict:
    """취소 전에 보여줄 금액: 구간 결제액, 수수료, 환불액."""
    pax = db.q("SELECT passenger_type FROM passenger WHERE booking_id = %s", (booking_id,))
    billable = int((pax.passenger_type != "INFANT").sum())
    infants = len(pax) - billable
    segs = db.q(
        """SELECT bs.segment_id, fa.base_price, fa.cancellation_fee
           FROM booking_segment bs JOIN fare fa ON bs.fare_id = fa.fare_id
           WHERE bs.booking_id = %s AND bs.segment_id = ANY(%s) AND bs.segment_status = 'ACTIVE'""",
        (booking_id, list(segment_ids)),
    )
    paid = sum(segment_price(r.base_price, billable, infants) for r in segs.itertuples())
    fee = int(segs.cancellation_fee.sum()) * billable if not segs.empty else 0
    return {"paid": paid, "fee": min(fee, paid), "refund": max(0, paid - fee), "billable": billable}


def cancel_segments(booking_id: int, segment_ids: list[int]) -> dict:
    """
    구간 단위 취소. 좌석을 풀고, 판매 좌석을 되돌리고, 환불을 기록한다.
    환불은 현금성 결제(카드·이체·간편결제)에 먼저 돌려주고,
    그것으로 모자라는 부분(마일리지로 낸 몫)은 마일리지로 되돌려 준다.
    모든 구간이 취소되면 예약도 취소 상태가 된다.
    """
    quote = cancel_quote(booking_id, segment_ids)
    billable = quote["billable"]
    with db.tx() as cur:
        for seg_id in segment_ids:
            cur.execute(
                """UPDATE booking_segment SET segment_status = 'CANCELLED'
                   WHERE segment_id = %s AND booking_id = %s AND segment_status = 'ACTIVE'
                   RETURNING fare_id""",
                (seg_id, booking_id),
            )
            row = cur.fetchone()
            if not row:
                continue
            cur.execute("DELETE FROM seat_assignment WHERE segment_id = %s", (seg_id,))
            cur.execute(
                "UPDATE fare SET seats_sold = GREATEST(seats_sold - %s, 0) WHERE fare_id = %s",
                (billable, row[0]),
            )

        left = quote["refund"]
        cur.execute(
            """SELECT payment_id, amount - refund_amount FROM payment
               WHERE booking_id = %s AND payment_method <> 'MILEAGE'
                 AND payment_status = 'COMPLETED' AND amount > refund_amount
               ORDER BY payment_id FOR UPDATE""",
            (booking_id,),
        )
        for pay_id, room in cur.fetchall():
            if left <= 0:
                break
            give = min(room, left)
            cur.execute(
                """UPDATE payment
                   SET refund_amount = refund_amount + %s,
                       payment_status = CASE WHEN refund_amount + %s >= amount
                                             THEN 'REFUNDED' ELSE payment_status END
                   WHERE payment_id = %s""",
                (give, give, pay_id),
            )
            left -= give

        back_miles = 0
        if left > 0:
            cur.execute(
                """SELECT ma.mileage_id, b.booking_pnr FROM booking b
                   JOIN mileage_account ma ON b.member_id = ma.member_id
                   WHERE b.booking_id = %s""",
                (booking_id,),
            )
            acc = cur.fetchone()
            if acc:
                back_miles = left // MILE_WON
                if back_miles > 0:
                    cur.execute(
                        """INSERT INTO mileage_history
                             (mileage_id, change_type, amount, remaining_amount, expire_at, reason)
                           VALUES (%s, 'EARN', %s, %s, CURRENT_DATE + %s * INTERVAL '1 year', %s)""",
                        (acc[0], back_miles, back_miles, EARN_YEARS, f"예약 {acc[1]} 취소 환급"),
                    )
                    cur.execute(
                        """UPDATE mileage_account
                           SET current_balance = current_balance + %s, last_updated_at = NOW()
                           WHERE mileage_id = %s""",
                        (back_miles, acc[0]),
                    )

        cur.execute(
            """UPDATE booking SET booking_status = 'CANCELLED'
               WHERE booking_id = %s
                 AND NOT EXISTS (SELECT 1 FROM booking_segment
                                 WHERE booking_id = %s AND segment_status <> 'CANCELLED')""",
            (booking_id, booking_id),
        )
    quote["back_miles"] = back_miles
    return quote


# ---------------------------------------------------------------- 체크인·탑승

def check_in(seat_assign_ids: list[int]) -> int:
    with db.tx() as cur:
        cur.execute(
            """UPDATE seat_assignment SET checked_in_at = NOW()
               WHERE seat_assign_id = ANY(%s) AND checked_in_at IS NULL""",
            (list(seat_assign_ids),),
        )
        return cur.rowcount


def set_boarded(changes: dict[int, bool]) -> None:
    """{seat_assign_id: 탑승 여부}. 체크인하지 않은 승객은 탑승 처리할 수 없다."""
    with db.tx() as cur:
        for sid, val in changes.items():
            cur.execute(
                """UPDATE seat_assignment SET is_boarded = %s
                   WHERE seat_assign_id = %s AND (checked_in_at IS NOT NULL OR %s = FALSE)""",
                (bool(val), int(sid), bool(val)),
            )


def complete_schedule(schedule_id: int) -> list[str]:
    """
    운항 완료 처리. 탑승객이 있는 구간을 FLOWN으로 바꾸고 마일리지를 적립한다.
    적립 조건: 회원 연결 + 실제 탑승 + 구간 완료. 셋 중 하나라도 빠지면 쌓이지 않는다.
    """
    earned = []
    with db.tx() as cur:
        cur.execute(
            """SELECT bs.segment_id FROM booking_segment bs
               WHERE bs.schedule_id = %s AND bs.segment_status = 'ACTIVE'
                 AND EXISTS (SELECT 1 FROM seat_assignment sa
                             WHERE sa.segment_id = bs.segment_id AND sa.is_boarded)""",
            (schedule_id,),
        )
        seg_ids = [r[0] for r in cur.fetchall()]

        for seg_id in seg_ids:
            cur.execute(
                "UPDATE booking_segment SET segment_status = 'FLOWN' WHERE segment_id = %s",
                (seg_id,),
            )
            cur.execute(
                """SELECT p.last_name, p.first_name, ma.mileage_id, f.flight_number,
                          (r.distance_km * fa.mileage_rate / 100)::int AS miles
                   FROM seat_assignment sa
                   JOIN passenger p        ON sa.passenger_id = p.passenger_id
                   JOIN mileage_account ma ON p.member_id = ma.member_id
                   JOIN booking_segment bs ON sa.segment_id = bs.segment_id
                   JOIN fare fa            ON bs.fare_id = fa.fare_id
                   JOIN flight_schedule fs ON bs.schedule_id = fs.schedule_id
                   JOIN flight f           ON fs.flight_number = f.flight_number
                   JOIN route r            ON f.route_id = r.route_id
                   WHERE sa.segment_id = %s AND sa.is_boarded""",
                (seg_id,),
            )
            for ln, fn, mid, flight_no, m in cur.fetchall():
                if m <= 0:
                    continue
                cur.execute(
                    """INSERT INTO mileage_history
                         (mileage_id, segment_id, change_type, amount, remaining_amount, expire_at, reason)
                       VALUES (%s, %s, 'EARN', %s, %s, CURRENT_DATE + %s * INTERVAL '1 year', %s)""",
                    (mid, seg_id, m, m, EARN_YEARS, f"{flight_no} 탑승 적립"),
                )
                cur.execute(
                    """UPDATE mileage_account
                       SET current_balance = current_balance + %s, last_updated_at = NOW()
                       WHERE mileage_id = %s""",
                    (m, mid),
                )
                earned.append(f"{ln}/{fn} +{m:,}")

        cur.execute(
            "UPDATE flight_schedule SET flight_status = 'COMPLETED' WHERE schedule_id = %s",
            (schedule_id,),
        )
    return earned


# ---------------------------------------------------------------- 마일리지 소멸

def expire_miles(mileage_id: int) -> int:
    """만료일이 지난 적립 건의 잔여량을 소멸시킨다. 소멸된 마일 합계를 돌려준다."""
    total = 0
    with db.tx() as cur:
        cur.execute(
            """SELECT history_id, remaining_amount FROM mileage_history
               WHERE mileage_id = %s AND change_type = 'EARN'
                 AND remaining_amount > 0 AND expire_at < CURRENT_DATE
               FOR UPDATE""",
            (mileage_id,),
        )
        for hid, left in cur.fetchall():
            cur.execute(
                """INSERT INTO mileage_history (mileage_id, change_type, amount, remaining_amount, reason)
                   VALUES (%s, 'EXPIRE', %s, 0, %s)""",
                (mileage_id, left, f"이력 {hid} 유효기간 만료"),
            )
            cur.execute("UPDATE mileage_history SET remaining_amount = 0 WHERE history_id = %s", (hid,))
            total += left
        if total:
            cur.execute(
                """UPDATE mileage_account
                   SET current_balance = current_balance - %s, last_updated_at = NOW()
                   WHERE mileage_id = %s""",
                (total, mileage_id),
            )
    return total
