"""
예약 상세 화면 조각 — 고객 '예약 조회'와 관리자 '예약 관리'가 함께 쓴다.
"""
import pandas as pd
import streamlit as st

import db
import services
import ui


def load(booking_id: int) -> dict | None:
    head = db.q(
        """SELECT b.booking_id, b.booking_pnr, b.booking_date, b.total_price, b.booking_status,
                  b.contact_email, m.member_name, m.email AS member_email
           FROM booking b LEFT JOIN member m ON b.member_id = m.member_id
           WHERE b.booking_id = %s""",
        (booking_id,),
    )
    if head.empty:
        return None
    segs = db.q(
        """SELECT bs.segment_id, bs.segment_order, bs.segment_status,
                  fs.schedule_id, fs.flight_date, fs.flight_status, fs.terminal, fs.gate,
                  f.flight_number, f.std_dep_time, f.std_arr_time,
                  r.dep_airport_code, r.arr_airport_code, r.flight_duration,
                  da.city AS dep_city, aa.city AS arr_city,
                  fa.seat_class, fa.fare_code, fa.base_price, fa.cancellation_fee
           FROM booking_segment bs
           JOIN flight_schedule fs ON bs.schedule_id = fs.schedule_id
           JOIN flight f  ON fs.flight_number = f.flight_number
           JOIN route r   ON f.route_id = r.route_id
           JOIN airport da ON r.dep_airport_code = da.airport_code
           JOIN airport aa ON r.arr_airport_code = aa.airport_code
           JOIN fare fa   ON bs.fare_id = fa.fare_id
           WHERE bs.booking_id = %s ORDER BY bs.segment_order""",
        (booking_id,),
    )
    pax = db.q(
        """SELECT p.passenger_id, p.last_name, p.first_name, p.birth_date, p.passenger_type,
                  p.member_id
           FROM passenger p WHERE p.booking_id = %s ORDER BY p.passenger_id""",
        (booking_id,),
    )
    seats = db.q(
        """SELECT sa.seat_assign_id, sa.segment_id, sa.passenger_id, st.seat_number,
                  sa.checked_in_at, sa.is_boarded
           FROM seat_assignment sa
           JOIN booking_segment bs ON sa.segment_id = bs.segment_id
           JOIN seat st ON sa.seat_id = st.seat_id
           WHERE bs.booking_id = %s""",
        (booking_id,),
    )
    pays = db.q(
        """SELECT payment_id, payment_method, amount, refund_amount, payment_status, payment_date
           FROM payment WHERE booking_id = %s ORDER BY payment_id""",
        (booking_id,),
    )
    return {"head": head.iloc[0], "segs": segs, "pax": pax, "seats": seats, "pays": pays}


def cancellable(data: dict) -> pd.DataFrame:
    """취소할 수 있는 구간: 예정 상태이고, 운항 전이며, 탑승 처리된 승객이 없는 구간."""
    segs = data["segs"]
    boarded = set(data["seats"][data["seats"].is_boarded == True].segment_id) if not data["seats"].empty else set()  # noqa: E712
    return segs[
        (segs.segment_status == "ACTIVE")
        & segs.flight_status.isin(["SCHEDULED", "DELAYED"])
        & ~segs.segment_id.isin(boarded)
    ]


@st.dialog("예약 취소")
def cancel_dialog(booking_id: int):
    data = load(booking_id)
    options = cancellable(data)
    if options.empty:
        st.write("취소할 수 있는 구간이 없습니다.")
        return
    multi = len(data["segs"]) > 1
    chosen = []
    for s in options.itertuples():
        label = (
            f"{s.flight_number} {s.dep_airport_code} → {s.arr_airport_code} · "
            f"{ui.kdate(s.flight_date)} {ui.hhmm(s.std_dep_time)}"
        )
        if not multi or st.checkbox(label, value=True, key=f"cx_{s.segment_id}"):
            chosen.append(int(s.segment_id))
        if not multi:
            st.write(label)
    if not chosen:
        st.caption("취소할 구간을 선택하세요.")
        return
    quote = services.cancel_quote(booking_id, chosen)
    st.html(
        ui.kv("취소 구간 결제액", ui.won(quote["paid"]))
        + ui.kv("취소 수수료", f"-{quote['fee']:,}원")
        + ui.kv("환불 예정 금액", ui.won(quote["refund"]), total=True)
    )
    st.caption("카드·이체·간편결제로 낸 금액에서 먼저 환불하고, 마일리지로 낸 몫은 마일리지로 돌려드립니다.")
    c1, c2 = st.columns(2)
    if c1.button("닫기", width="stretch"):
        st.rerun()
    if c2.button("취소하기", type="primary", width="stretch"):
        try:
            res = services.cancel_segments(booking_id, chosen)
        except Exception:
            st.error("취소 처리 중 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.")
            return
        msg = f"취소되었습니다. 환불 {ui.won(res['refund'])}"
        if res.get("back_miles"):
            msg += f" (이 중 {res['back_miles']:,}M는 마일리지로 환급)"
        st.session_state["flash_ok"] = msg
        st.rerun()


def render(booking_id: int, *, admin: bool = False, on_checkin=None):
    data = load(booking_id)
    if data is None:
        st.warning("예약을 찾을 수 없습니다.")
        return
    h, segs, pax, seats, pays = data["head"], data["segs"], data["pax"], data["seats"], data["pays"]

    checked = not seats.empty and seats.checked_in_at.notna().any()
    flown = not segs.empty and (segs.segment_status == "FLOWN").all()

    with st.container(border=True):
        c1, c2 = st.columns([3, 1], vertical_alignment="center")
        c1.html(
            f'<h3 style="margin:0">예약번호 {ui.esc(h.booking_pnr)} &nbsp;'
            f'{ui.booking_badge(h.booking_status, checked, flown)}</h3>'
        )
        who = h.member_name or "비회원"
        c2.html(f'<div class="sky-muted" style="text-align:right">예약일 {str(h.booking_date)[:10]} · {ui.esc(who)}</div>')

        for s in segs.itertuples():
            name = ("가는 편" if s.segment_order == 1 else "오는 편") if len(segs) == 2 else f"{s.segment_order}구간"
            if len(segs) == 1:
                name = "항공편 정보"
            seg_badge = ui.badge(ui.SEG_KO.get(s.segment_status, s.segment_status),
                                 "muted" if s.segment_status == "CANCELLED" else "outline")
            st.html(f'<h4 style="margin:14px 0 6px">{name} &nbsp;{seg_badge}</h4>')
            cols = st.columns(4)
            ui.stat_card(cols[0], "편명", s.flight_number, f"{ui.CLASS_KO.get(s.seat_class)} · {ui.FARE_KO.get(s.fare_code, s.fare_code)}")
            ui.stat_card(cols[1], "출발", f"{s.dep_airport_code} {ui.hhmm(s.std_dep_time)}", f"{s.dep_city} · {ui.kdate(s.flight_date)}")
            ui.stat_card(cols[2], "도착", f"{s.arr_airport_code} {ui.hhmm(s.std_arr_time)}", f"{s.arr_city} · {ui.kdate(s.flight_date)}")
            gate = f" · 탑승구 {s.gate}" if s.gate else ""
            ui.stat_card(cols[3], "소요 시간", ui.duration(s.flight_duration), f"{ui.FLIGHT_KO.get(s.flight_status)}{gate}")

        st.html('<h4 style="margin:18px 0 6px">탑승객 · 좌석</h4>')
        rows = []
        for i, p in enumerate(pax.itertuples(), start=1):
            mine = seats[seats.passenger_id == p.passenger_id] if not seats.empty else seats
            seat_parts, ci = [], []
            for s in segs.itertuples():
                m = mine[mine.segment_id == s.segment_id] if not mine.empty else mine
                if m.empty:
                    seat_parts.append("-" if p.passenger_type != "INFANT" else "보호자 동반")
                    ci.append("-")
                else:
                    r = m.iloc[0]
                    seat_parts.append(r.seat_number)
                    ci.append("탑승" if r.is_boarded else ("완료" if pd.notna(r.checked_in_at) else "미완료"))
            rows.append({
                "탑승객": f"탑승객 {i}",
                "영문명": f"{p.last_name}/{p.first_name}",
                "구분": ui.PAX_KO.get(p.passenger_type),
                "생년월일": str(p.birth_date),
                "좌석": " / ".join(dict.fromkeys(seat_parts)) if len(set(seat_parts)) == 1 else " / ".join(seat_parts),
                "체크인": " / ".join(ci),
            })
        ui.table(pd.DataFrame(rows))

        st.html('<h4 style="margin:18px 0 6px">결제 정보</h4>')
        paid = pays[pays.payment_status.isin(["COMPLETED", "REFUNDED"])] if not pays.empty else pays
        total_paid = int(paid.amount.sum()) if not paid.empty else 0
        refunded = int(paid.refund_amount.sum()) if not paid.empty else 0
        methods = ", ".join(dict.fromkeys(ui.PAY_KO.get(m, m) for m in paid.payment_method)) if not paid.empty else "-"
        mile_used = int(paid[paid.payment_method == "MILEAGE"].amount.sum() // services.MILE_WON) if not paid.empty else 0
        pay_date = str(paid.payment_date.min())[:10] if not paid.empty else "-"
        cols = st.columns(4)
        ui.stat_card(cols[0], "결제 금액", ui.won(total_paid), f"환불 {ui.won(refunded)}" if refunded else None)
        ui.stat_card(cols[1], "결제 수단", methods, small=True)
        ui.stat_card(cols[2], "사용 마일리지", ui.miles(mile_used))
        ui.stat_card(cols[3], "결제일", pay_date)

        can_cancel = not cancellable(data).empty
        can_checkin = (segs.segment_status == "ACTIVE").any() and h.booking_status != "CANCELLED"
        b1, b2, _ = st.columns([1, 1, 4])
        if on_checkin and can_checkin:
            if b1.button("체크인 하기", width="stretch"):
                on_checkin(h.booking_pnr, pax.iloc[0].last_name)
        if can_cancel and b2.button("예약 취소", width="stretch", key=f"cancel_{booking_id}"):
            cancel_dialog(booking_id)
