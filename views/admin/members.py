"""관리자 · 회원 관리 — 회원 목록, 등급 변경, 만료 마일리지 소멸 처리"""
import pandas as pd
import streamlit as st

import db
import services
import ui

if not db.current_admin():
    st.stop()

S = st.session_state
if "flash_ok" in S:
    st.success(S.pop("flash_ok"))

st.title("회원 관리")

with st.container(border=True):
    c1, c2 = st.columns([2, 1])
    kw = c1.text_input("이름 · 이메일 · 전화번호")
    tier = c2.selectbox("등급", [""] + list(ui.TIER_KO), format_func=lambda t: "전체" if not t else ui.TIER_KO[t])

df = db.q(
    """SELECT m.member_id, m.member_name, m.email, m.phone, m.join_date,
              ma.mileage_id, ma.tier, ma.current_balance,
              (SELECT count(*) FROM booking b WHERE b.member_id = m.member_id) AS bookings,
              (SELECT COALESCE(SUM(remaining_amount), 0) FROM mileage_history h
                WHERE h.mileage_id = ma.mileage_id AND h.change_type = 'EARN'
                  AND h.remaining_amount > 0 AND h.expire_at < CURRENT_DATE) AS expired
       FROM member m LEFT JOIN mileage_account ma ON m.member_id = ma.member_id
       WHERE (%s = '' OR m.member_name ILIKE %s OR m.email ILIKE %s OR m.phone ILIKE %s)
         AND (%s = '' OR ma.tier = %s)
       ORDER BY m.member_id""",
    (kw.strip(), f"%{kw.strip()}%", f"%{kw.strip()}%", f"%{kw.strip()}%", tier, tier),
)

if df.empty:
    with st.container(border=True):
        st.write("조건에 맞는 회원이 없습니다.")
    st.stop()

view = pd.DataFrame({
    "회원번호": df.member_id,
    "이름": df.member_name,
    "이메일": df.email,
    "전화번호": df.phone.fillna("-"),
    "가입일": df.join_date.astype(str).str[:10],
    "등급": df.tier.map(ui.TIER_KO),
    "마일리지": df.current_balance.fillna(0).astype(int),
    "예약 수": df.bookings,
})
event = st.dataframe(view, hide_index=True, width="stretch", on_select="rerun",
                     selection_mode="single-row", key="mb_table")
st.caption(f"총 {len(df)}명 · 행을 선택하면 등급 변경과 마일리지 소멸 처리를 할 수 있습니다.")

rows = event.selection.rows if event else []
if not rows:
    st.stop()

row = df.iloc[rows[0]]
st.subheader(f"{row.member_name} 회원")
c1, c2 = st.columns(2)

with c1.container(border=True):
    st.markdown("**회원 등급**")
    tiers = list(ui.TIER_KO)
    new_tier = st.selectbox("등급", tiers, index=tiers.index(row.tier) if row.tier in tiers else 0,
                            format_func=ui.TIER_KO.get, key=f"tier_{row.member_id}")
    if st.button("등급 저장", disabled=new_tier == row.tier):
        db.execute("UPDATE mileage_account SET tier = %s, last_updated_at = NOW() WHERE member_id = %s",
                   (new_tier, int(row.member_id)))
        S["flash_ok"] = f"{row.member_name} 회원 등급을 {ui.TIER_KO[new_tier]}(으)로 바꿨습니다."
        st.rerun()

with c2.container(border=True):
    st.markdown("**만료 마일리지 소멸**")
    expired = int(row.expired or 0)
    st.write(f"만료일이 지났지만 아직 남아 있는 마일리지: **{expired:,} M**")
    if st.button("소멸 처리", disabled=expired == 0 or pd.isna(row.mileage_id)):
        total = services.expire_miles(int(row.mileage_id))
        S["flash_ok"] = f"{row.member_name} 회원의 마일리지 {total:,} M를 소멸 처리했습니다."
        st.rerun()
