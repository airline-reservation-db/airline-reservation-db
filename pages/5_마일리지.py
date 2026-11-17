"""
마일리지 — 잔액, 변동 이력, 소멸 예정

담당: 회원·마일리지 도메인
핵심: 잔액은 적립 건별 잔여량의 합이다. 이력이 원본이고 잔액은 캐시다.
"""
import streamlit as st

import db

st.set_page_config(page_title="마일리지", page_icon="✦", layout="wide")

me = db.sidebar_auth()
st.title("마일리지")

# 마일리지 계좌는 회원에게만 있다(mileage_account.member_id 가 NOT NULL).
# 비회원은 쌓을 곳도 쓸 곳도 없으므로 이 화면은 로그인을 요구한다.
me = db.require_login("마일리지는 회원 전용입니다.")
member_id = me["member_id"]
st.caption(f"{me['member_name']} 님")

acc = db.q(
    """SELECT mileage_id, current_balance, tier, last_updated_at
       FROM mileage_account WHERE member_id = %s""",
    (member_id,),
)
if acc.empty:
    st.warning("마일리지 계좌가 없습니다.")
    st.stop()

acc = acc.iloc[0]
mileage_id = int(acc.mileage_id)

# 요약 -------------------------------------------------------------------
lifetime = db.q1(
    """SELECT COALESCE(SUM(amount), 0) FROM mileage_history
       WHERE mileage_id = %s AND change_type = 'EARN'""",
    (mileage_id,),
)
expiring = db.q1(
    """SELECT COALESCE(SUM(remaining_amount), 0) FROM mileage_history
       WHERE mileage_id = %s AND change_type = 'EARN'
         AND remaining_amount > 0
         AND expire_at <= CURRENT_DATE + INTERVAL '1 year'""",
    (mileage_id,),
)
c = st.columns(4)
c[0].metric("보유 마일리지", f"{int(acc.current_balance):,}")
c[1].metric("누적 적립", f"{int(lifetime):,}")
c[2].metric("회원 등급", acc.tier)
c[3].metric("1년 내 소멸 예정", f"{int(expiring):,}", delta=None)

if expiring > 0:
    st.warning(f"1년 이내에 **{int(expiring):,} 마일**이 소멸될 예정입니다.")

st.divider()

# 변동 이력 ---------------------------------------------------------------
st.subheader("변동 이력")

HISTORY = """
SELECT h.history_id AS "이력",
       h.change_date::date AS "처리일",
       h.change_type AS "유형",
       h.amount AS "변동량",
       h.remaining_amount AS "잔여량",
       h.expire_at AS "만료일",
       CASE
         WHEN h.segment_id IS NOT NULL
           THEN f.flight_number || ' ' || r.dep_airport_code || '→' || r.arr_airport_code
         WHEN h.payment_id IS NOT NULL
           THEN '결제 ' || p.payment_id::text
         ELSE '-'
       END AS "근거",
       h.reason AS "사유"
FROM mileage_history h
LEFT JOIN booking_segment bs ON h.segment_id = bs.segment_id
LEFT JOIN flight_schedule fs ON bs.schedule_id = fs.schedule_id
LEFT JOIN flight f           ON fs.flight_number = f.flight_number
LEFT JOIN route  r           ON f.route_id = r.route_id
LEFT JOIN payment p          ON h.payment_id = p.payment_id
WHERE h.mileage_id = %s
ORDER BY h.change_date DESC, h.history_id DESC
"""
hist = db.q(HISTORY, (mileage_id,))

if hist.empty:
    st.info("변동 내역이 없습니다.")
else:
    st.dataframe(hist, use_container_width=True, hide_index=True)

# 선입선출 차감 순서 -------------------------------------------------------
st.subheader("다음에 차감될 순서")
st.caption("마일리지를 사용하면 만료일이 빠른 적립 건부터 깎입니다.")

fifo = db.q(
    """SELECT history_id AS "이력", change_date::date AS "적립일",
              amount AS "적립량", remaining_amount AS "잔여량",
              expire_at AS "만료일",
              (expire_at - CURRENT_DATE) AS "남은 일수"
       FROM mileage_history
       WHERE mileage_id = %s AND change_type = 'EARN' AND remaining_amount > 0
       ORDER BY expire_at""",
    (mileage_id,),
)
if fifo.empty:
    st.info("사용 가능한 적립 건이 없습니다.")
else:
    st.dataframe(fifo, use_container_width=True, hide_index=True)

# 소멸 처리 ---------------------------------------------------------------
st.divider()
st.subheader("소멸 처리")

expired = db.q(
    """SELECT history_id, remaining_amount, expire_at
       FROM mileage_history
       WHERE mileage_id = %s AND change_type = 'EARN'
         AND remaining_amount > 0 AND expire_at < CURRENT_DATE""",
    (mileage_id,),
)
if expired.empty:
    st.caption("만료된 적립 건이 없습니다.")
else:
    total = int(expired.remaining_amount.sum())
    st.warning(f"만료일이 지난 적립 건 {len(expired)}건, 합계 {total:,} 마일")
    if st.button("소멸 처리 실행", type="primary"):
        try:
            with db.tx() as cur:
                for r in expired.itertuples():
                    cur.execute(
                        """INSERT INTO mileage_history
                             (mileage_id, change_type, amount, remaining_amount, reason)
                           VALUES (%s, 'EXPIRE', %s, 0, %s)""",
                        (mileage_id, int(r.remaining_amount),
                         f"이력 {r.history_id} 유효기간 만료"),
                    )
                    cur.execute(
                        "UPDATE mileage_history SET remaining_amount = 0 WHERE history_id = %s",
                        (int(r.history_id),),
                    )
                cur.execute(
                    """UPDATE mileage_account
                       SET current_balance = current_balance - %s, last_updated_at = NOW()
                       WHERE mileage_id = %s""",
                    (total, mileage_id),
                )
        except Exception as e:
            st.error("소멸 처리에 실패했습니다.")
            st.code(str(e))
        else:
            st.success(f"{total:,} 마일을 소멸 처리했습니다.")
            st.rerun()
