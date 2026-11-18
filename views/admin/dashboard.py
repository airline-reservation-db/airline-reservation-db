"""관리자 · 대시보드"""
import datetime as dt
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st

import db
import ui

if not db.current_admin():
    st.stop()

TODAY = dt.datetime.now(ZoneInfo("Asia/Seoul")).date()
MONTH1 = TODAY.replace(day=1)
PREV1 = (MONTH1 - dt.timedelta(days=1)).replace(day=1)
WEEK1 = TODAY - dt.timedelta(days=TODAY.weekday())

h1, h2 = st.columns([3, 1], vertical_alignment="bottom")
h1.title("대시보드")
h2.html(f'<div class="sky-muted" style="text-align:right">{ui.kdate(TODAY)} 기준</div>')

k = db.q(
    """SELECT
         (SELECT count(*) FROM booking WHERE booking_date::date = %(t)s) AS today_bk,
         (SELECT count(*) FROM booking WHERE booking_date::date = %(t)s - 1) AS yday_bk,
         (SELECT COALESCE(SUM(amount - refund_amount), 0) FROM payment
           WHERE payment_status IN ('COMPLETED','REFUNDED') AND payment_date >= %(m1)s) AS month_rev,
         (SELECT COALESCE(SUM(amount - refund_amount), 0) FROM payment
           WHERE payment_status IN ('COMPLETED','REFUNDED')
             AND payment_date >= %(p1)s AND payment_date < %(m1)s) AS prev_rev,
         (SELECT ROUND(100.0 * SUM(fa.seats_sold) / NULLIF(SUM(fa.seats_allotted), 0), 1)
            FROM fare fa JOIN flight_schedule fs ON fa.schedule_id = fs.schedule_id
           WHERE fs.flight_date BETWEEN %(t)s - 30 AND %(t)s AND fs.flight_status <> 'CANCELLED') AS load30,
         (SELECT count(*) FROM member WHERE join_date >= %(w1)s) AS new_members,
         (SELECT count(*) FROM member) AS members""",
    {"t": TODAY, "m1": MONTH1, "p1": PREV1, "w1": WEEK1},
).iloc[0]

c = st.columns(4)
diff = int(k.today_bk) - int(k.yday_bk)
ui.stat_card(c[0], "오늘 예약 수", f"{int(k.today_bk):,}건", f"전일 대비 {diff:+d}건")
ui.stat_card(c[1], "이번 달 매출", ui.won(k.month_rev), f"지난달 {ui.won(k.prev_rev)} (환불 차감)")
ui.stat_card(c[2], "평균 탑승률", f"{float(k.load30 or 0):.1f}%", "최근 30일 운항편 · 판매석 ÷ 공급석")
ui.stat_card(c[3], "신규 회원 수", f"{int(k.new_members):,}명", f"이번 주 가입 · 전체 {int(k.members):,}명")

c1, c2, c3 = st.columns(3)

with c1.container(border=True):
    st.markdown("**노선별 예약률**")
    lf = db.q(
        """SELECT r.dep_airport_code || '-' || r.arr_airport_code AS route,
                  ROUND(100.0 * SUM(fa.seats_sold) / NULLIF(SUM(fa.seats_allotted), 0), 1) AS rate
           FROM fare fa
           JOIN flight_schedule fs ON fa.schedule_id = fs.schedule_id
           JOIN flight f ON fs.flight_number = f.flight_number
           JOIN route r ON f.route_id = r.route_id
           WHERE fs.flight_date >= %s AND fs.flight_status <> 'CANCELLED'
           GROUP BY 1 ORDER BY rate DESC LIMIT 6""",
        (TODAY,),
    )
    if lf.empty:
        st.caption("예정된 운항편이 없습니다.")
    else:
        lf["rate"] = lf.rate.astype(float)
        st.altair_chart(
            alt.Chart(lf).mark_bar(color="#0B5FFF", cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
            .encode(x=alt.X("route:N", sort="-y", title=None, axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("rate:Q", title="예약률(%)"),
                    tooltip=[alt.Tooltip("route", title="노선"), alt.Tooltip("rate", title="예약률(%)")])
            .properties(height=230),
            use_container_width=True,
        )
    st.caption("앞으로 운항할 편 기준")

with c2.container(border=True):
    st.markdown("**일별 매출 (최근 30일)**")
    rev = db.q(
        """SELECT payment_date::date AS day, SUM(amount - refund_amount) AS revenue
           FROM payment WHERE payment_status IN ('COMPLETED','REFUNDED')
             AND payment_date::date > %s - 30
           GROUP BY 1 ORDER BY 1""",
        (TODAY,),
    )
    days = pd.DataFrame({"day": pd.date_range(TODAY - dt.timedelta(days=29), TODAY)})
    if not rev.empty:
        rev["day"] = pd.to_datetime(rev.day)
        days = days.merge(rev, on="day", how="left")
    days["revenue"] = days.get("revenue", pd.Series(dtype=float)).fillna(0).astype(float)
    st.altair_chart(
        alt.Chart(days).mark_line(color="#0B5FFF", point=True)
        .encode(x=alt.X("day:T", title=None, axis=alt.Axis(format="%m-%d")),
                y=alt.Y("revenue:Q", title="매출(원)"),
                tooltip=[alt.Tooltip("day:T", title="날짜"), alt.Tooltip("revenue:Q", title="매출", format=",")])
        .properties(height=230),
        use_container_width=True,
    )
    st.caption("결제 완료액 − 환불액")

with c3.container(border=True):
    st.markdown("**회원 등급 분포**")
    tiers = db.q("SELECT tier, count(*) AS n FROM mileage_account GROUP BY tier")
    if tiers.empty:
        st.caption("회원이 없습니다.")
    else:
        tiers["등급"] = tiers.tier.map(ui.TIER_KO)
        tiers["n"] = tiers.n.astype(int)
        st.altair_chart(
            alt.Chart(tiers).mark_arc(innerRadius=55)
            .encode(theta="n:Q",
                    color=alt.Color("등급:N", scale=alt.Scale(
                        domain=["브론즈", "실버", "골드", "플래티넘"],
                        range=["#C9CDD4", "#8A93A3", "#0B5FFF", "#111418"]),
                        legend=alt.Legend(orient="bottom", title=None)),
                    tooltip=["등급", alt.Tooltip("n", title="회원 수")])
            .properties(height=230),
            use_container_width=True,
        )
        total = tiers.n.sum()
        st.caption(" · ".join(f"{r.등급} {r.n * 100 // total}%" for r in tiers.itertuples()))
