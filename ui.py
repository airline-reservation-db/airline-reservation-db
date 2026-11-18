"""
화면 공통 요소 — 스타일, 라벨, 카드·배지·단계 표시 같은 작은 HTML 조각.

DB 값(영문 코드)을 화면용 한글로 바꾸는 사전도 여기에 모은다.
"""
import datetime as dt
import html as _html

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------- 라벨

CLASS_KO = {"ECONOMY": "이코노미", "BUSINESS": "비즈니스", "FIRST": "퍼스트"}
FARE_KO = {"Q": "특가", "M": "할인", "Y": "정규", "C": "정규"}
PAX_KO = {"ADULT": "성인", "CHILD": "소아", "INFANT": "유아"}
TIER_KO = {"BRONZE": "브론즈", "SILVER": "실버", "GOLD": "골드", "PLATINUM": "플래티넘"}
NEXT_TIER = {"BRONZE": "실버", "SILVER": "골드", "GOLD": "플래티넘", "PLATINUM": "최고 등급"}
FLIGHT_KO = {"SCHEDULED": "정상", "DELAYED": "지연", "CANCELLED": "결항", "COMPLETED": "운항완료"}
BOOKING_KO = {"PENDING": "결제 대기", "CONFIRMED": "확정", "TICKETED": "확정", "CANCELLED": "취소"}
SEG_KO = {"ACTIVE": "예정", "CANCELLED": "취소", "FLOWN": "탑승 완료"}
PAY_KO = {"CARD": "신용카드", "BANK": "계좌이체", "EASY_PAY": "간편결제", "MILEAGE": "마일리지"}
CHANGE_KO = {"EARN": "적립", "USE": "사용", "EXPIRE": "소멸"}

WEEK = "월화수목금토일"


def esc(v) -> str:
    return _html.escape("" if v is None else str(v))


def won(v) -> str:
    return "-" if v is None or pd.isna(v) else f"{int(v):,}원"


def miles(v) -> str:
    return f"{int(v or 0):,} M"


def hhmm(t) -> str:
    return "-" if t is None else str(t)[:5]


def duration(minutes) -> str:
    h, m = divmod(int(minutes), 60)
    return f"{h}시간 {m}분" if m else f"{h}시간"


def kdate(d) -> str:
    """2026-12-20(일)"""
    if d is None:
        return "-"
    d = pd.to_datetime(d).date()
    return f"{d.isoformat()}({WEEK[d.weekday()]})"


def add_minutes(t, minutes: int) -> str:
    base = dt.datetime.combine(dt.date.today(), t) if isinstance(t, dt.time) else pd.to_datetime(str(t))
    return (base + dt.timedelta(minutes=minutes)).strftime("%H:%M")


# ---------------------------------------------------------------- 스타일

CSS = """
<style>
:root {
  --sky-blue: #0B5FFF;
  --sky-ink: #111418;
  --sky-sub: #5F6672;
  --sky-line: #DADDE3;
  --sky-soft: #F4F5F7;
}
html, body, [class*="st-"], .stMarkdown, button, input, textarea {
  font-family: "Pretendard", -apple-system, "Apple SD Gothic Neo", "Noto Sans KR",
               "Segoe UI", Roboto, sans-serif;
}
.block-container { max-width: 1180px; padding-top: 2.2rem; }
h1 { font-size: 1.85rem !important; font-weight: 800 !important; letter-spacing: -0.02em; }
h2, h3 { letter-spacing: -0.01em; }

/* 공통 조각 */
.sky-sub { color: var(--sky-sub); font-size: 0.95rem; margin: -0.4rem 0 1.2rem; }
.sky-muted { color: var(--sky-sub); font-size: 0.85rem; }
.sky-bar {
  background: var(--sky-soft); border-radius: 10px; padding: 14px 20px;
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 0.6rem;
}
.sky-bar b { font-size: 1.05rem; }
.sky-badge {
  display: inline-block; border-radius: 999px; padding: 1px 10px; font-size: 0.78rem;
  font-weight: 600; line-height: 1.6; white-space: nowrap; vertical-align: middle;
}
.sky-badge.dark { background: var(--sky-ink); color: #fff; }
.sky-badge.blue { background: var(--sky-blue); color: #fff; }
.sky-badge.outline { border: 1px solid var(--sky-ink); color: var(--sky-ink); }
.sky-badge.muted { background: #E4E6EA; color: #6B717C; }

.sky-label { color: var(--sky-sub); font-size: 0.82rem; margin-bottom: 2px; }
.sky-value { font-size: 1.55rem; font-weight: 800; letter-spacing: -0.02em; line-height: 1.25; }
.sky-value.sm { font-size: 1.15rem; }
.sky-note { color: var(--sky-sub); font-size: 0.82rem; margin-top: 2px; }

/* 항공편 카드 */
.sky-flight { display: flex; align-items: center; gap: 28px; flex-wrap: wrap; }
.sky-flight .no b { font-size: 1.02rem; }
.sky-flight .t { font-size: 1.45rem; font-weight: 800; line-height: 1.1; }
.sky-flight .ap { color: var(--sky-sub); font-size: 0.82rem; }
.sky-flight .mid { text-align: center; color: var(--sky-sub); font-size: 0.78rem; min-width: 96px; }
.sky-flight .mid hr { margin: 4px 0 0; border: 0; border-top: 1px solid #B9BEC6; }
.sky-price { text-align: right; }
.sky-price .p { font-size: 1.3rem; font-weight: 800; }
.sky-price .left { color: var(--sky-sub); font-size: 0.82rem; }

/* 단계 표시 */
.sky-steps { display: flex; justify-content: center; align-items: center; gap: 12px;
             margin: 0.2rem 0 1.4rem; flex-wrap: wrap; }
.sky-steps .s { display: flex; align-items: center; gap: 8px; color: var(--sky-sub); font-size: 0.92rem; }
.sky-steps .n { width: 26px; height: 26px; border-radius: 50%; display: inline-flex;
                align-items: center; justify-content: center; font-size: 0.8rem; font-weight: 700;
                border: 1.5px solid #B9BEC6; color: #8A909A; }
.sky-steps .s.on { color: var(--sky-ink); font-weight: 700; }
.sky-steps .s.on .n, .sky-steps .s.done .n { background: var(--sky-ink); border-color: var(--sky-ink); color: #fff; }
.sky-steps .line { width: 56px; height: 1.5px; background: #B9BEC6; }

/* 요약 표 */
.sky-kv { display: flex; justify-content: space-between; padding: 4px 0; font-size: 0.93rem; }
.sky-kv span:first-child { color: var(--sky-sub); }
.sky-kv.total { border-top: 1px solid var(--sky-line); margin-top: 8px; padding-top: 12px; }
.sky-kv.total span:first-child { color: var(--sky-ink); font-weight: 700; }
.sky-kv.total span:last-child { font-size: 1.5rem; font-weight: 800; }

/* 표 */
.sky-table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 0.92rem;
             border: 1px solid var(--sky-line); border-radius: 10px; overflow: hidden; }
.sky-table th { background: var(--sky-soft); text-align: left; font-weight: 600; color: var(--sky-sub);
                padding: 10px 14px; border-bottom: 1px solid var(--sky-line); }
.sky-table td { padding: 10px 14px; border-bottom: 1px solid #ECEEF1; }
.sky-table tr:last-child td { border-bottom: 0; }

/* 탑승권 */
.sky-pass { border: 1.5px solid var(--sky-ink); border-radius: 12px; overflow: hidden; }
.sky-pass .top { background: #E4E6EA; padding: 12px 22px; display: flex; justify-content: space-between;
                 align-items: center; }
.sky-pass .top b { font-size: 1.15rem; letter-spacing: 0.02em; }
.sky-pass .body { padding: 18px 22px 20px; }
.sky-pass .route { display: flex; justify-content: space-between; align-items: center;
                   border-bottom: 1px solid var(--sky-line); padding-bottom: 14px; margin-bottom: 14px; }
.sky-pass .code { font-size: 2.3rem; font-weight: 800; line-height: 1.1; }
.sky-pass .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px 10px; }
.sky-pass .grid b { font-size: 1.05rem; }
.sky-pass .pnr { margin-top: 16px; background: var(--sky-soft); border-radius: 8px; padding: 14px;
                 text-align: center; font-family: ui-monospace, Menlo, monospace; letter-spacing: 0.35em;
                 font-size: 1.2rem; font-weight: 700; }

/* 예약 완료 */
.sky-done { text-align: center; }
.sky-done .check { width: 44px; height: 44px; border-radius: 50%; background: var(--sky-ink); color: #fff;
                   display: inline-flex; align-items: center; justify-content: center; font-size: 1.4rem; }
.sky-done .pnr { background: #E4E6EA; border-radius: 10px; padding: 16px; margin: 14px 0 6px;
                 font-size: 2.1rem; font-weight: 800; letter-spacing: 0.08em; }

/* 좌석 배치도 — 버튼을 작게, 열이 좁은 화면에서도 줄바꿈되지 않게 */
.st-key-seatmap { background: var(--sky-soft); border-radius: 22px; padding: 14px 16px 18px;
                  max-width: 430px; margin: 0 auto; }
.st-key-seatmap [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: 6px !important; }
.st-key-seatmap [data-testid="stColumn"] { min-width: 0 !important; flex: 1 1 0 !important; width: auto !important; }
.st-key-seatmap button { min-height: 32px !important; height: 32px; padding: 0 !important; }
.st-key-seatmap button p { font-size: 0.72rem !important; }
.st-key-seatmap .rowno { text-align: center; color: var(--sky-sub); font-size: 0.75rem; line-height: 32px; }
.st-key-seatmap .colhd { text-align: center; color: var(--sky-sub); font-size: 0.75rem; }
.seat-legend { display: flex; gap: 16px; align-items: center; font-size: 0.82rem; color: var(--sky-sub);
               flex-wrap: wrap; justify-content: flex-end; }
.seat-legend i { display: inline-block; width: 16px; height: 16px; border-radius: 4px; margin-right: 6px;
                 vertical-align: -3px; border: 1px solid #B9BEC6; background: #fff; }
.seat-legend i.sel { background: var(--sky-blue); border-color: var(--sky-blue); }
.seat-legend i.taken { background: #E4E6EA; border-color: #E4E6EA; }
.seat-legend i.biz { border: 2px solid var(--sky-ink); }

/* 관리자 미리보기용 좌석 배치(읽기 전용) */
.sky-seatview { background: var(--sky-soft); border-radius: 18px; padding: 14px; display: inline-block; }
.sky-seatview table { border-collapse: separate; border-spacing: 4px; margin: 0 auto; }
.sky-seatview td { width: 32px; height: 26px; text-align: center; font-size: 0.66rem; border-radius: 5px;
                   background: #fff; border: 1px solid #C9CDD4; }
.sky-seatview td.biz { border: 2px solid var(--sky-ink); font-weight: 700; }
.sky-seatview td.aisle, .sky-seatview td.hd { background: transparent; border: 0; color: var(--sky-sub); }
.sky-seatview .cap { text-align: center; color: var(--sky-sub); font-size: 0.75rem; margin: 6px 0 2px; }

/* 상단 메뉴: 회원가입·로그인 / 마이페이지·로그아웃을 오른쪽 끝으로 */
[data-testid="stHeader"] .rc-overflow { flex: 1 1 auto !important; width: 100%; }
.rc-overflow-item:has(a[data-testid="stTopNavLink"][href$="/signup"]),
.rc-overflow-item:has(a[data-testid="stTopNavLink"][href$="/mypage"]) { margin-left: auto !important; }

/* 관리자 사이드바 */
section[data-testid="stSidebar"] { background: #F1F2F4; }
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------- 조각

def html(s: str):
    st.markdown(s, unsafe_allow_html=True)


def badge(text: str, kind: str = "dark") -> str:
    return f'<span class="sky-badge {kind}">{esc(text)}</span>'


def booking_badge(status: str, checked_in: bool = False, flown: bool = False) -> str:
    if status == "CANCELLED":
        return badge("취소", "muted")
    if flown:
        return badge("탑승 완료", "outline")
    if checked_in:
        return badge("체크인 완료", "outline")
    return badge(BOOKING_KO.get(status, status), "dark")


def flight_badge(status: str) -> str:
    kind = {"SCHEDULED": "outline", "DELAYED": "dark", "CANCELLED": "muted", "COMPLETED": "muted"}
    return badge(FLIGHT_KO.get(status, status), kind.get(status, "outline"))


def title(text: str, sub: str | None = None):
    st.title(text)
    if sub:
        html(f'<div class="sky-sub">{esc(sub)}</div>')


def stat(label: str, value: str, note: str | None = None, small: bool = False):
    """테두리 카드 안에 들어가는 라벨·큰 값·보조 문구."""
    note_html = f'<div class="sky-note">{esc(note)}</div>' if note else ""
    cls = "sky-value sm" if small else "sky-value"
    html(f'<div class="sky-label">{esc(label)}</div><div class="{cls}">{esc(value)}</div>{note_html}')


def stat_card(col, label, value, note=None, small=False):
    with col.container(border=True):
        stat(label, value, note, small)


def kv(label: str, value: str, total: bool = False) -> str:
    cls = "sky-kv total" if total else "sky-kv"
    return f'<div class="{cls}"><span>{esc(label)}</span><span>{esc(value)}</span></div>'


def steps(labels: list[str], current: int):
    parts = []
    for i, label in enumerate(labels):
        state = "on" if i == current else ("done" if i < current else "")
        parts.append(f'<div class="s {state}"><span class="n">{i + 1}</span>{esc(label)}</div>')
        if i < len(labels) - 1:
            parts.append('<div class="line"></div>')
    html(f'<div class="sky-steps">{"".join(parts)}</div>')


def table(df: pd.DataFrame, raw_cols: tuple = ()):
    """간단한 읽기 전용 표. raw_cols 열은 HTML(배지 등)을 그대로 넣는다."""
    head = "".join(f"<th>{esc(c)}</th>" for c in df.columns)
    rows = []
    for _, r in df.iterrows():
        cells = "".join(
            f"<td>{r[c] if c in raw_cols else esc(r[c])}</td>" for c in df.columns
        )
        rows.append(f"<tr>{cells}</tr>")
    html(f'<table class="sky-table"><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>')


def flight_html(no, dep_time, arr_time, dep_code, arr_code, dep_city, arr_city, minutes, sub="직항") -> str:
    return f"""
<div class="sky-flight">
  <div class="no"><b>{esc(no)}</b><div class="ap">{esc(sub)}</div></div>
  <div><div class="t">{esc(hhmm(dep_time))}</div><div class="ap">{esc(dep_code)} {esc(dep_city)}</div></div>
  <div class="mid">{esc(duration(minutes))}<hr></div>
  <div><div class="t">{esc(hhmm(arr_time))}</div><div class="ap">{esc(arr_code)} {esc(arr_city)}</div></div>
</div>"""


# ---------------------------------------------------------------- 좌석 배치

def split_seat(seat_number: str) -> tuple[int, str]:
    return int(seat_number[:-1]), seat_number[-1]


def seat_blocks(seats: pd.DataFrame) -> list[dict]:
    """
    좌석 목록을 등급별 블록으로 묶는다.
    블록마다 행 번호 목록과 열 문자(왼쪽/오른쪽 통로 기준)를 계산한다.
    """
    blocks = []
    order = {"FIRST": 0, "BUSINESS": 1, "ECONOMY": 2}
    for cls in sorted(seats.seat_class.unique(), key=lambda c: order.get(c, 9)):
        part = seats[seats.seat_class == cls]
        rc = [split_seat(s) for s in part.seat_number]
        rows = sorted({r for r, _ in rc})
        letters = sorted({c for _, c in rc})
        half = (len(letters) + 1) // 2
        blocks.append({
            "cls": cls,
            "rows": rows,
            "left": letters[:half],
            "right": letters[half:],
        })
    return blocks


def seat_view_html(seats: pd.DataFrame) -> str:
    """관리자 화면용 읽기 전용 좌석 배치도."""
    out = ['<div class="sky-seatview">']
    for b in seat_blocks(seats):
        n = len(b["left"]) + len(b["right"])
        out.append(
            f'<div class="cap">{CLASS_KO.get(b["cls"], b["cls"])} '
            f'({b["rows"][0]}~{b["rows"][-1]}열 · {len(b["left"])}-{len(b["right"])} 배열 · '
            f'{len(b["rows"]) * n}석)</div>'
        )
        out.append("<table>")
        hd = "".join(f'<td class="hd">{c}</td>' for c in b["left"]) + '<td class="hd"></td>' + "".join(
            f'<td class="hd">{c}</td>' for c in b["right"])
        out.append(f"<tr>{hd}</tr>")
        cls = "biz" if b["cls"] != "ECONOMY" else ""
        for r in b["rows"]:
            cells = "".join(f'<td class="{cls}">{r}{c}</td>' for c in b["left"])
            cells += f'<td class="aisle">{r}</td>'
            cells += "".join(f'<td class="{cls}">{r}{c}</td>' for c in b["right"])
            out.append(f"<tr>{cells}</tr>")
        out.append("</table>")
    out.append("</div>")
    return "".join(out)
