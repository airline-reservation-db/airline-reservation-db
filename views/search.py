"""
항공편 검색 → 결과 → 좌석 선택 → 예약 정보·결제 → 완료

한 페이지 안에서 단계(step)를 바꿔 가며 진행한다.
진행 상태는 st.session_state["bk"] 하나에 모은다.
"""
import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from psycopg2 import errors as pgerr

import db
import services
import ui

S = st.session_state
KST = ZoneInfo("Asia/Seoul")
NOW = dt.datetime.now(KST).replace(tzinfo=None)
TODAY = NOW.date()

if "bk" not in S:
    S["bk"] = {"step": "search"}

# 검색 폼 값은 결과·좌석 단계에서 위젯이 안 그려져도 유지되어야
# '검색 조건 수정'으로 돌아왔을 때 그대로 남는다. (Streamlit은 안 그려진 위젯 상태를 지운다)
for _k in ("f_trip", "f_dep", "f_arr", "f_d1", "f_d2", "f_cls", "f_adult", "f_child", "f_infant"):
    if _k in S:
        S[_k] = S[_k]
bk = S["bk"]
me = db.current_member()

if "flash" in S:
    st.warning(S.pop("flash"))


def go(step: str, **extra):
    bk["step"] = step
    bk.update(extra)
    st.rerun()


# ---------------------------------------------------------------- 기준 데이터

@st.cache_data(ttl=600)
def airport_table() -> pd.DataFrame:
    return db.q("SELECT airport_code, airport_name, city FROM airport ORDER BY airport_code")


AP = airport_table()
CODES = AP.airport_code.tolist()
CITY = dict(zip(AP.airport_code, AP.city))


def ap_label(code: str) -> str:
    return f"{code} {CITY.get(code, '')}"


CLASSES = db.q("SELECT DISTINCT seat_class FROM fare").seat_class.tolist()
CLASSES = [c for c in ("ECONOMY", "BUSINESS", "FIRST") if c in CLASSES]

SEARCH_SQL = """
SELECT fs.schedule_id, fs.aircraft_id, fs.flight_date, fs.flight_status, fs.terminal, fs.gate,
       f.flight_number, f.std_dep_time, f.std_arr_time,
       r.dep_airport_code, r.arr_airport_code, r.distance_km, r.flight_duration,
       ac.model_name,
       fa.fare_id, fa.seat_class, fa.fare_code, fa.base_price, fa.cancellation_fee,
       fa.mileage_rate,
       -- 남은 자리 = 운임 잔여석과 실제 빈 좌석(같은 등급) 중 작은 값
       LEAST(fa.seats_allotted - fa.seats_sold,
             (SELECT count(*) FROM seat s
               WHERE s.aircraft_id = fs.aircraft_id AND s.seat_class = fa.seat_class)
           - (SELECT count(*) FROM seat_assignment sa
               JOIN booking_segment bs ON sa.segment_id = bs.segment_id
               JOIN seat s ON sa.seat_id = s.seat_id
               WHERE bs.schedule_id = fs.schedule_id AND bs.segment_status <> 'CANCELLED'
                 AND s.seat_class = fa.seat_class)) AS seats_left
FROM flight_schedule fs
JOIN flight   f  ON fs.flight_number = f.flight_number
JOIN route    r  ON f.route_id       = r.route_id
JOIN aircraft ac ON fs.aircraft_id   = ac.aircraft_id
JOIN fare     fa ON fa.schedule_id   = fs.schedule_id
WHERE r.dep_airport_code = %s AND r.arr_airport_code = %s
  AND fs.flight_date = %s AND fa.seat_class = %s
  AND fs.flight_status IN ('SCHEDULED', 'DELAYED')
ORDER BY f.std_dep_time, fa.base_price
"""


def seats_needed() -> int:
    return bk["adult"] + bk["child"]


def pax_list() -> list[dict]:
    """탑승객 목록(성인 → 소아 → 유아 순서). 좌석은 성인·소아만."""
    out = []
    for t, n in (("ADULT", bk["adult"]), ("CHILD", bk["child"]), ("INFANT", bk["infant"])):
        for _ in range(n):
            out.append({"type": t})
    for i, p in enumerate(out):
        p["label"] = f"탑승객 {i + 1} · {ui.PAX_KO[p['type']]}"
    return out


def leg_info(leg: int) -> tuple[str, str, dt.date]:
    if leg == 0:
        return bk["dep"], bk["arr"], bk["d1"]
    return bk["arr"], bk["dep"], bk["d2"]


def leg_name(leg: int) -> str:
    return "가는 편" if leg == 0 else "오는 편"


def condition_text() -> str:
    trip = "왕복" if bk["trip"] == "왕복" else "편도"
    dates = ui.kdate(bk["d1"]) + (f" ~ {ui.kdate(bk['d2'])}" if bk["trip"] == "왕복" else "")
    pax = f"성인 {bk['adult']}, 소아 {bk['child']}" + (f", 유아 {bk['infant']}" if bk["infant"] else "")
    return f"{trip} · {dates} · {pax} · {ui.CLASS_KO[bk['cls']]}"


# ================================================================ 1. 검색

def _swap():
    S["f_dep"], S["f_arr"] = S["f_arr"], S["f_dep"]


def _start_search(dep=None, arr=None):
    if dep:
        S["f_dep"], S["f_arr"] = dep, arr
    for k in [k for k in S.keys() if str(k).startswith("flt_")]:
        del S[k]
    bk.clear()
    bk.update({
        "step": "results", "leg": 0,
        "trip": S["f_trip"], "dep": S["f_dep"], "arr": S["f_arr"],
        "d1": S["f_d1"], "d2": S["f_d2"], "cls": S["f_cls"],
        "adult": S["f_adult"], "child": S["f_child"], "infant": S["f_infant"],
        "segs": {}, "seats": {}, "seat_seg": 0,
    })


def step_search():
    S.setdefault("f_trip", "왕복")
    S.setdefault("f_dep", "GMP" if "GMP" in CODES else CODES[0])
    S.setdefault("f_arr", "CJU" if "CJU" in CODES else CODES[1])
    S.setdefault("f_d1", TODAY + dt.timedelta(days=7))
    S.setdefault("f_d2", TODAY + dt.timedelta(days=10))
    S.setdefault("f_cls", CLASSES[0])
    S.setdefault("f_adult", 1)
    S.setdefault("f_child", 0)
    S.setdefault("f_infant", 0)

    ui.title("어디로 떠나시나요?", "출발지와 도착지, 날짜를 선택해 항공편을 검색하세요")

    with st.container(border=True):
        st.radio("여정", ["왕복", "편도"], horizontal=True, key="f_trip", label_visibility="collapsed")
        c1, c2, c3 = st.columns([12, 1, 12], vertical_alignment="bottom")
        c1.selectbox("출발 공항", CODES, format_func=ap_label, key="f_dep")
        c2.button("⇄", on_click=_swap, help="출발·도착 바꾸기", width="stretch")
        c3.selectbox("도착 공항", CODES, format_func=ap_label, key="f_arr")

        c4, c5, c6 = st.columns(3)
        c4.date_input("가는 날", key="f_d1", min_value=TODAY)
        c5.date_input("오는 날", key="f_d2", min_value=TODAY, disabled=S["f_trip"] == "편도")
        c6.selectbox("좌석 등급", CLASSES, format_func=ui.CLASS_KO.get, key="f_cls")

        c7, c8, c9, c10 = st.columns([1, 1, 1, 2], vertical_alignment="bottom")
        c7.selectbox("성인", range(1, 10), format_func=lambda n: f"{n}명", key="f_adult")
        c8.selectbox("소아 (만 2~11세)", range(0, 9), format_func=lambda n: f"{n}명", key="f_child")
        c9.selectbox("유아 (만 2세 미만)", range(0, 5), format_func=lambda n: f"{n}명", key="f_infant")
        clicked = c10.button("항공편 검색", type="primary", width="stretch")

    if clicked:
        problems = []
        if S["f_dep"] == S["f_arr"]:
            problems.append("출발 공항과 도착 공항이 같습니다.")
        if S["f_trip"] == "왕복" and S["f_d2"] < S["f_d1"]:
            problems.append("오는 날이 가는 날보다 빠릅니다.")
        if S["f_adult"] + S["f_child"] > 9:
            problems.append("좌석이 필요한 승객(성인+소아)은 최대 9명까지 예약할 수 있습니다.")
        if S["f_infant"] > S["f_adult"]:
            problems.append("유아는 성인 1명당 1명까지 동반할 수 있습니다.")
        if problems:
            for p in problems:
                st.warning(p)
        else:
            _start_search()
            st.rerun()

    # 인기 노선: 앞으로 운항할 편 중 판매 좌석이 많은 노선
    popular = db.q(
        """SELECT r.dep_airport_code AS dep, r.arr_airport_code AS arr,
                  MIN(fa.base_price) FILTER (WHERE fa.seat_class = 'ECONOMY') AS from_price,
                  SUM(fa.seats_sold) AS sold
           FROM flight_schedule fs
           JOIN flight f ON fs.flight_number = f.flight_number
           JOIN route r  ON f.route_id = r.route_id
           JOIN fare fa  ON fa.schedule_id = fs.schedule_id
           WHERE fs.flight_date >= %s AND fs.flight_status IN ('SCHEDULED','DELAYED')
           GROUP BY r.dep_airport_code, r.arr_airport_code
           ORDER BY sold DESC, from_price
           LIMIT 3""",
        (TODAY,),
    )
    if not popular.empty:
        st.subheader("인기 노선")
        cols = st.columns(3)
        for col, r in zip(cols, popular.itertuples()):
            with col.container(border=True):
                ui.html(
                    f'<div class="sky-value sm">{ui.esc(r.dep)} → {ui.esc(r.arr)}</div>'
                    f'<div class="sky-muted">{ui.esc(CITY.get(r.dep))} → {ui.esc(CITY.get(r.arr))}</div>'
                    f'<div style="font-weight:700;margin-top:4px">{ui.won(r.from_price)}~</div>'
                )
                st.button("이 노선 검색", key=f"pop_{r.dep}_{r.arr}", on_click=_start_search,
                          args=(r.dep, r.arr), type="tertiary")


# ================================================================ 2. 결과

TIME_SLOTS = [
    ("새벽 00:00~06:00", 0, 6),
    ("오전 06:00~12:00", 6, 12),
    ("오후 12:00~18:00", 12, 18),
    ("저녁 18:00~24:00", 18, 24),
]


def _reset_filters():
    for k in [k for k in S.keys() if str(k).startswith("flt_")]:
        del S[k]


def _pick_fare(leg: int, row: dict):
    bk["segs"][leg] = row
    bk["seats"].pop(leg, None)
    _reset_filters()
    if bk["trip"] == "왕복" and leg == 0:
        bk["leg"] = 1
    else:
        bk["step"] = "seats"
        bk["seat_seg"] = 0


def step_results():
    leg = bk["leg"]
    dep, arr, date = leg_info(leg)

    with st.container():
        c1, c2 = st.columns([5, 1], vertical_alignment="center")
        c1.html(
            f'<div class="sky-bar"><b>{ui.esc(ap_label(bk["dep"]))} → {ui.esc(ap_label(bk["arr"]))}</b>'
            f'<span class="sky-muted">{ui.esc(condition_text())}</span></div>'
        )
        if c2.button("검색 조건 수정", width="stretch"):
            go("search")

    if leg == 1 and 0 in bk["segs"]:
        s0 = bk["segs"][0]
        c1, c2 = st.columns([5, 1], vertical_alignment="center")
        c1.html(
            f'<div class="sky-muted">{ui.badge("가는 편", "outline")} &nbsp;<b>{ui.esc(s0["flight_number"])}</b> '
            f'{ui.esc(s0["dep"])} {ui.hhmm(s0["dep_time"])} → {ui.esc(s0["arr"])} {ui.hhmm(s0["arr_time"])} · '
            f'{ui.kdate(s0["date"])} · {ui.won(s0["base_price"])} 선택됨</div>'
        )
        if c2.button("가는 편 다시 선택", type="tertiary"):
            bk["leg"] = 0
            st.rerun()

    rows = db.q(SEARCH_SQL, (dep, arr, date, bk["cls"]))
    if not rows.empty:
        departs = pd.to_datetime(rows.flight_date.astype(str) + " " + rows.std_dep_time.astype(str))
        rows = rows[departs > NOW]

    need = seats_needed()
    flights = []
    for sid, g in rows.groupby("schedule_id", sort=False):
        ok = g[g.seats_left >= need]
        best = ok.iloc[0] if not ok.empty else None
        flights.append({"head": g.iloc[0], "fares": g, "best": best})

    left, right = st.columns([1, 3], gap="medium")

    with left.container(border=True):
        st.subheader("필터")
        st.caption("출발 시간대")
        slot_on = [st.checkbox(name, value=True, key=f"flt_t{i}") for i, (name, _, _) in enumerate(TIME_SLOTS)]
        prices = [int(f["best"].base_price) for f in flights if f["best"] is not None]
        price_rng = None
        if len(set(prices)) > 1:
            st.divider()
            st.caption("가격 범위")
            price_rng = st.slider(
                "가격", min(prices), max(prices), (min(prices), max(prices)),
                step=1000, format="%d원", key="flt_price", label_visibility="collapsed",
            )
        st.divider()
        only_avail = st.checkbox("예약 가능한 편만 보기", value=False, key="flt_avail")
        st.button("필터 초기화", on_click=_reset_filters)

    def visible(f):
        hour = int(str(f["head"].std_dep_time)[:2])
        slot = next(i for i, (_, a, b) in enumerate(TIME_SLOTS) if a <= hour < b)
        if not slot_on[slot]:
            return False
        if f["best"] is None:
            return not only_avail
        if price_rng and not (price_rng[0] <= f["best"].base_price <= price_rng[1]):
            return False
        return True

    shown = [f for f in flights if visible(f)]

    with right:
        h1, h2 = st.columns([3, 1], vertical_alignment="bottom")
        h1.html(
            f'<h3 style="margin:0">{leg_name(leg)} 선택 '
            f'<span class="sky-muted" style="font-weight:400;font-size:0.85rem">'
            f'{ui.esc(ap_label(dep))} → {ui.esc(ap_label(arr))} · {ui.kdate(date)} · {len(shown)}개 항공편</span></h3>'
        )
        sort = h2.selectbox("정렬", ["가격순", "출발 시간순"], key="flt_sort", label_visibility="collapsed")
        if sort == "가격순":
            shown.sort(key=lambda f: (f["best"] is None, 0 if f["best"] is None else f["best"].base_price))

        if not shown:
            with st.container(border=True):
                st.write("조건에 맞는 항공편이 없습니다.")
                st.caption("날짜나 필터를 바꿔 보세요.")

        for f in shown:
            h, best = f["head"], f["best"]
            with st.container(border=True):
                c1, c2, c3 = st.columns([5, 2.2, 1.1], vertical_alignment="center")
                sub = "지연" if h.flight_status == "DELAYED" else f"직항 · {h.model_name}"
                c1.html(ui.flight_html(
                    h.flight_number, h.std_dep_time, h.std_arr_time,
                    h.dep_airport_code, h.arr_airport_code,
                    CITY.get(h.dep_airport_code), CITY.get(h.arr_airport_code),
                    h.flight_duration, sub,
                ))
                if best is None:
                    c2.html('<div class="sky-price"><div class="left">잔여석 부족</div><div class="p">매진</div></div>')
                    c3.button("선택", key=f"pick_{h.schedule_id}", disabled=True, width="stretch")
                    continue
                c2.html(
                    f'<div class="sky-price"><div class="left">잔여 {int(best.seats_left)}석 · '
                    f'{ui.FARE_KO.get(best.fare_code, best.fare_code)}</div>'
                    f'<div class="p">{ui.won(best.base_price)}</div></div>'
                )

                def row_of(fr):
                    return {
                        "schedule_id": int(fr.schedule_id), "fare_id": int(fr.fare_id),
                        "aircraft_id": int(fr.aircraft_id), "flight_number": fr.flight_number,
                        "date": fr.flight_date, "dep": fr.dep_airport_code, "arr": fr.arr_airport_code,
                        "dep_time": fr.std_dep_time, "arr_time": fr.std_arr_time,
                        "minutes": int(fr.flight_duration), "seat_class": fr.seat_class,
                        "fare_code": fr.fare_code, "base_price": int(fr.base_price),
                        "cancellation_fee": int(fr.cancellation_fee),
                        "distance": int(fr.distance_km), "mileage_rate": int(fr.mileage_rate),
                        "gate": fr.gate, "terminal": fr.terminal, "model": fr.model_name,
                    }

                c3.button("선택", key=f"pick_{h.schedule_id}", type="primary", width="stretch",
                          on_click=_pick_fare, args=(leg, row_of(best)))

                if len(f["fares"]) > 1:
                    with c2.popover("운임 비교"):
                        for fr in f["fares"].itertuples():
                            a, b = st.columns([3, 1], vertical_alignment="center")
                            a.markdown(
                                f"**{ui.FARE_KO.get(fr.fare_code, fr.fare_code)} ({fr.fare_code})** "
                                f"{ui.won(fr.base_price)}  \n"
                                f":gray[잔여 {int(fr.seats_left)}석 · 취소 수수료 {ui.won(fr.cancellation_fee)} · "
                                f"적립률 {int(fr.mileage_rate)}%]"
                            )
                            b.button("선택", key=f"pickf_{fr.fare_id}", disabled=fr.seats_left < need,
                                     on_click=_pick_fare, args=(leg, row_of(fr)))


# ================================================================ 3. 좌석

def _seat_click(seg_i: int, seat_id: int, seat_no: str, order: list[int]):
    picks = bk["seats"].setdefault(seg_i, {})
    owner = next((p for p, v in picks.items() if v[0] == seat_id), None)
    key = f"seat_active_{seg_i}"
    if owner is not None:
        del picks[owner]
        S[key] = owner
        return
    active = S.get(key, order[0])
    picks[active] = (seat_id, seat_no)
    nxt = next((p for p in order if p not in picks), None)
    if nxt is not None:
        S[key] = nxt


def step_seats():
    seg_i = bk["seat_seg"]
    seg = bk["segs"][seg_i]
    pax = pax_list()
    order = [i for i, p in enumerate(pax) if p["type"] != "INFANT"]
    picks = bk["seats"].setdefault(seg_i, {})

    c1, c2 = st.columns([5, 1], vertical_alignment="center")
    c1.html(
        f'<div class="sky-bar">{ui.badge(leg_name(seg_i), "outline")} <b>{ui.esc(seg["flight_number"])}</b>'
        f'<span>{ui.esc(ap_label(seg["dep"]))} {ui.hhmm(seg["dep_time"])} → '
        f'{ui.esc(ap_label(seg["arr"]))} {ui.hhmm(seg["arr_time"])}</span>'
        f'<span class="sky-muted">{ui.kdate(seg["date"])} · {ui.CLASS_KO[seg["seat_class"]]} · '
        f'{len(order)}명 좌석</span></div>'
    )
    if c2.button("항공편 변경", type="tertiary"):
        bk["leg"] = seg_i
        go("results")

    seats = db.q("SELECT seat_id, seat_number, seat_class FROM seat WHERE aircraft_id = %s", (seg["aircraft_id"],))
    taken = set(db.q(
        """SELECT sa.seat_id FROM seat_assignment sa
           JOIN booking_segment bs ON sa.segment_id = bs.segment_id
           WHERE bs.schedule_id = %s AND bs.segment_status <> 'CANCELLED'""",
        (seg["schedule_id"],),
    ).get("seat_id", pd.Series(dtype=int)).tolist())
    # 다른 사람이 그사이 가져간 좌석은 선택에서 뺀다
    for p, (sid, _) in list(picks.items()):
        if sid in taken:
            del picks[p]

    left, right = st.columns([1.6, 1], gap="medium")

    with left.container(border=True):
        h1, h2 = st.columns([1, 2], vertical_alignment="center")
        h1.subheader("좌석 선택")
        h2.html(
            '<div class="seat-legend"><span><i></i>선택 가능</span><span><i class="sel"></i>선택됨</span>'
            '<span><i class="taken"></i>예약됨·선택 불가</span><span><i class="biz"></i>비즈니스</span></div>'
        )
        chosen_ids = {v[0] for v in picks.values()}
        by_no = {r.seat_number: (int(r.seat_id), r.seat_class) for r in seats.itertuples()}

        with st.container(key="seatmap"):
            ui.html('<div class="colhd">▲ 기수(앞) 방향</div>')
            for b in ui.seat_blocks(seats):
                n = len(b["left"]) + len(b["right"])
                ui.html(
                    f'<div class="colhd" style="margin-top:8px">{ui.CLASS_KO[b["cls"]]} '
                    f'({b["rows"][0]}~{b["rows"][-1]}열 · {len(b["left"])}-{len(b["right"])} 배열)</div>'
                )
                hd = st.columns(n + 1)
                for j, c in enumerate(b["left"] + [""] + b["right"]):
                    hd[j].html(f'<div class="colhd">{c or "통로"}</div>')
                for r in b["rows"]:
                    cols = st.columns(n + 1)
                    letters = b["left"] + [None] + b["right"]
                    for j, c in enumerate(letters):
                        if c is None:
                            cols[j].html(f'<div class="rowno">{r}</div>')
                            continue
                        no = f"{r}{c}"
                        if no not in by_no:
                            continue
                        sid, cls = by_no[no]
                        sel = sid in chosen_ids
                        cols[j].button(
                            no, key=f"seat_{seg_i}_{sid}",
                            type="primary" if sel else "secondary",
                            disabled=(sid in taken or cls != seg["seat_class"]) and not sel,
                            on_click=_seat_click, args=(seg_i, sid, no, order),
                            width="stretch",
                        )

    with right.container(border=True):
        st.subheader("선택한 좌석")
        key = f"seat_active_{seg_i}"
        if S.get(key) not in order:
            S[key] = next((p for p in order if p not in picks), order[0])
        st.radio(
            "좌석을 지정할 탑승객",
            order,
            key=key,
            format_func=lambda i: f"{pax[i]['label']} — " + (picks[i][1] if i in picks else "미지정"),
        )
        st.caption("탑승객을 고른 뒤 왼쪽 배치도에서 좌석을 누르세요. 선택한 좌석을 다시 누르면 취소됩니다.")
        if bk["infant"]:
            st.caption(f"유아 {bk['infant']}명은 보호자 좌석에 함께 앉습니다.")
        st.divider()
        all_set = all(p in picks for p in order)
        is_last = not (bk["trip"] == "왕복" and seg_i == 0)
        if st.button("다음" if is_last else "오는 편 좌석 선택", type="primary", width="stretch", disabled=not all_set):
            if is_last:
                go("info")
            else:
                bk["seat_seg"] = 1
                st.rerun()
        if st.button("이전", width="stretch"):
            if seg_i == 1:
                bk["seat_seg"] = 0
                st.rerun()
            bk["leg"] = 1 if bk["trip"] == "왕복" else 0
            go("results")


# ================================================================ 4. 예약 정보·결제

def _age_on(birth: dt.date, on: dt.date) -> int:
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def step_info():
    segs = [bk["segs"][i] for i in sorted(bk["segs"])]
    pax = pax_list()
    billable = bk["adult"] + bk["child"]
    infants = bk["infant"]
    first_date = pd.to_datetime(segs[0]["date"]).date()

    seat_txt = {}
    for i in range(len(pax)):
        parts = [bk["seats"].get(si, {}).get(i, (None, None))[1] for si in range(len(segs))]
        seat_txt[i] = " / ".join(p for p in parts if p) or "좌석 없음"

    sub = " · ".join(
        f'{s["flight_number"]} {s["dep"]} {ui.hhmm(s["dep_time"])} → {s["arr"]} {ui.hhmm(s["arr_time"])} '
        f'{ui.kdate(s["date"])}' for s in segs
    )
    ui.title("예약 정보 입력 · 결제", sub)

    left, right = st.columns([1.8, 1], gap="medium")

    with left:
        with st.container(border=True):
            st.subheader("예약자 정보")
            if me:
                st.write(f"**{me['member_name']}** 님 (회원 예약)")
                contact = st.text_input("연락 이메일", me["email"], key="inf_contact_m")
            else:
                st.caption("비회원 예약입니다. 예약번호와 탑승객 영문 성으로 예약을 조회할 수 있습니다.")
                contact = st.text_input("연락 이메일", key="inf_contact_g", placeholder="hong@example.com")

        with st.container(border=True):
            st.subheader("탑승객 정보")
            st.caption("여권에 적힌 영문 이름 그대로 입력하세요.")
            people = []
            self_idx = None
            for i, p in enumerate(pax):
                if i:
                    st.divider()
                st.markdown(f"**{p['label']} · {seat_txt[i]}**")
                c1, c2 = st.columns(2)
                last = c1.text_input("영문 성", key=f"inf_ln{i}", placeholder="HONG")
                first = c2.text_input("영문 이름", key=f"inf_fn{i}", placeholder="GILDONG")
                c3, c4, c5 = st.columns([1, 1, 0.9], vertical_alignment="bottom")
                default_birth = {"ADULT": dt.date(1995, 1, 1), "CHILD": TODAY.replace(year=TODAY.year - 6),
                                 "INFANT": TODAY.replace(year=TODAY.year - 1)}[p["type"]]
                birth = c3.date_input("생년월일", default_birth, min_value=dt.date(1920, 1, 1),
                                      max_value=TODAY, key=f"inf_bd{i}")
                passport = c4.text_input("여권번호 (선택)", key=f"inf_pp{i}", max_chars=20)
                is_self = False
                if me and p["type"] == "ADULT":
                    is_self = c5.checkbox("회원 본인", key=f"inf_self{i}", value=(i == 0))
                    if is_self:
                        self_idx = i if self_idx is None else self_idx
                people.append({
                    "last": last.strip().upper(), "first": first.strip().upper(),
                    "birth": birth, "passport": passport.strip().upper(), "type": p["type"],
                    "member_id": None, "is_self": is_self,
                })
            if me and self_idx is not None:
                people[self_idx]["member_id"] = me["member_id"]

        use_mile = 0
        balance = 0
        subtotal = sum(services.segment_price(s["base_price"], billable, infants) for s in segs)
        if me:
            balance = int(db.q1("SELECT current_balance FROM mileage_account WHERE member_id = %s",
                                (me["member_id"],)) or 0)
            max_mile = int(min(balance, subtotal // services.MILE_WON) // 100 * 100)
            with st.container(border=True):
                st.subheader("마일리지 사용")
                st.html(ui.kv("보유 마일리지", ui.miles(balance)))
                S.setdefault("inf_mile", 0)
                if S["inf_mile"] > max_mile:
                    S["inf_mile"] = max_mile
                c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
                use_mile = c1.number_input("사용할 마일리지", 0, max_mile, step=100, key="inf_mile")
                c2.button("전액 사용", width="stretch", on_click=lambda: S.update(inf_mile=max_mile),
                          disabled=max_mile == 0)
                st.caption(f"1M = {services.MILE_WON}원 · 100M 단위로 사용할 수 있습니다")

    total = subtotal - int(use_mile) * services.MILE_WON
    expected = 0
    if me and self_idx is not None:
        expected = sum(s["distance"] * s["mileage_rate"] // 100 for s in segs)

    with right.container(border=True):
        st.subheader("결제 요약")
        lines = []
        for i, s in enumerate(segs):
            name = leg_name(i) if len(segs) > 1 else "항공 운임"
            lines.append(ui.kv(f"{name} ({ui.FARE_KO.get(s['fare_code'], '')} · 좌석 {billable}명)",
                               ui.won(s["base_price"] * billable)))
            if infants:
                lines.append(ui.kv(f"{name} 유아 {infants}명 (10%)",
                                   ui.won(int(s["base_price"] * services.INFANT_RATE) * infants)))
        if use_mile:
            lines.append(ui.kv("마일리지 사용", f"-{int(use_mile) * services.MILE_WON:,}원"))
        lines.append(ui.kv("최종 결제 금액", ui.won(total), total=True))
        if me:
            lines.append(ui.kv("탑승 후 적립 예정", ui.miles(expected)))
        st.html("".join(lines))
        st.divider()
        method = st.radio("결제 수단", ["CARD", "BANK", "EASY_PAY"], format_func=ui.PAY_KO.get,
                          key="inf_method", disabled=total == 0)
        agree = st.checkbox("[필수] 운송약관 및 개인정보 이용 동의", key="inf_agree")

        missing = [p for p in people if not p["last"] or not p["first"]]
        wrong_age = []
        for p, info in zip(people, pax):
            age = _age_on(p["birth"], first_date)
            if info["type"] == "ADULT" and age < 12:
                wrong_age.append(f"{info['label']}: 성인은 만 12세 이상이어야 합니다.")
            if info["type"] == "CHILD" and not 2 <= age < 12:
                wrong_age.append(f"{info['label']}: 소아는 만 2~11세여야 합니다.")
            if info["type"] == "INFANT" and age >= 2:
                wrong_age.append(f"{info['label']}: 유아는 만 2세 미만이어야 합니다.")
        bad_email = "@" not in (contact or "")

        pay = st.button(f"{total:,}원 결제하기", type="primary", width="stretch",
                        disabled=bool(missing or wrong_age or bad_email or not agree))
        if missing:
            st.caption("탑승객 영문 성·이름을 모두 입력하세요.")
        elif bad_email:
            st.caption("연락 이메일을 입력하세요.")
        for w in wrong_age:
            st.caption(w)
        if st.button("이전", width="stretch"):
            bk["seat_seg"] = len(segs) - 1
            go("seats")

    if pay:
        seats = {si: {pi: v[0] for pi, v in bk["seats"].get(si, {}).items()} for si in range(len(segs))}
        try:
            booking_id, pnr = services.create_booking(
                booker_id=me["member_id"] if me else None,
                contact=contact.strip(),
                passengers=people,
                segments=segs,
                seats=seats,
                method=method if total > 0 else "CARD",
                use_mile=int(use_mile),
            )
        except pgerr.UniqueViolation:
            for si in range(len(segs)):
                bk["seats"][si] = {}
            S["flash"] = "선택한 좌석이 방금 다른 예약에 배정되었습니다. 좌석을 다시 선택해 주세요."
            bk["seat_seg"] = 0
            go("seats")
        except pgerr.CheckViolation:
            st.error("그사이 잔여석이나 마일리지가 부족해졌습니다. 다시 검색해 주세요.")
            return
        except Exception:
            st.error("결제 처리 중 문제가 생겨 예약이 저장되지 않았습니다. 잠시 후 다시 시도해 주세요.")
            return
        for k in [k for k in S.keys() if str(k).startswith(("inf_", "seat_active_"))]:
            del S[k]
        S["bk"] = {"step": "done", "booking_id": booking_id, "pnr": pnr}
        st.rerun()


# ================================================================ 5. 완료

def step_done():
    booking_id = bk["booking_id"]
    head = db.q(
        """SELECT b.booking_pnr, b.total_price, b.contact_email FROM booking b WHERE b.booking_id = %s""",
        (booking_id,),
    ).iloc[0]
    segs = db.q(
        """SELECT bs.segment_id, bs.segment_order, f.flight_number, fs.flight_date,
                  f.std_dep_time, f.std_arr_time, r.dep_airport_code, r.arr_airport_code, fa.seat_class
           FROM booking_segment bs
           JOIN flight_schedule fs ON bs.schedule_id = fs.schedule_id
           JOIN flight f ON fs.flight_number = f.flight_number
           JOIN route r ON f.route_id = r.route_id
           JOIN fare fa ON bs.fare_id = fa.fare_id
           WHERE bs.booking_id = %s ORDER BY bs.segment_order""",
        (booking_id,),
    )
    pax = db.q(
        """SELECT p.passenger_id, p.last_name || '/' || p.first_name AS name, p.passenger_type,
                  string_agg(st.seat_number, ' / ' ORDER BY bs.segment_order) AS seats
           FROM passenger p
           LEFT JOIN seat_assignment sa ON sa.passenger_id = p.passenger_id
           LEFT JOIN booking_segment bs ON sa.segment_id = bs.segment_id
           LEFT JOIN seat st ON sa.seat_id = st.seat_id
           WHERE p.booking_id = %s
           GROUP BY p.passenger_id ORDER BY p.passenger_id""",
        (booking_id,),
    )

    _, mid, _ = st.columns([1, 2.2, 1])
    with mid.container(border=True):
        ui.html(
            '<div class="sky-done"><div class="check">✓</div>'
            '<h2 style="margin:10px 0 2px">예약이 완료되었습니다</h2>'
            '<div class="sky-muted">예약번호와 탑승객 영문 성으로 예약 조회와 온라인 체크인을 할 수 있습니다</div>'
            f'<div class="pnr">{ui.esc(head.booking_pnr)}</div><div class="sky-muted">예약번호</div></div>'
        )
        st.subheader("여정")
        for s in segs.itertuples():
            name = leg_name(s.segment_order - 1) if len(segs) > 1 else "항공편"
            st.html(
                f'<div class="sky-kv"><span>{ui.badge(name, "outline")} &nbsp;<b>{ui.esc(s.flight_number)}</b> '
                f'{ui.esc(s.dep_airport_code)} {ui.hhmm(s.std_dep_time)} → {ui.esc(s.arr_airport_code)} '
                f'{ui.hhmm(s.std_arr_time)}</span><span>{ui.kdate(s.flight_date)} · '
                f'{ui.CLASS_KO.get(s.seat_class)}</span></div>'
            )
        st.subheader("탑승객")
        ui.table(pd.DataFrame({
            "탑승객": [f"탑승객 {i + 1}" for i in range(len(pax))],
            "영문명": pax["name"],
            "구분": pax.passenger_type.map(ui.PAX_KO),
            "좌석": pax.seats.fillna("보호자 동반"),
        }))
        st.html(ui.kv("결제 금액", ui.won(head.total_price), total=True))

        c1, c2 = st.columns(2)
        if c1.button("예약 상세 보기", type="primary", width="stretch"):
            S["view_booking"] = int(booking_id)
            S["bk"] = {"step": "search"}
            st.switch_page("views/lookup.py")
        if c2.button("메인으로", width="stretch"):
            S["bk"] = {"step": "search"}
            st.rerun()


# ================================================================ 실행

{
    "search": step_search,
    "results": step_results,
    "seats": step_seats,
    "info": step_info,
    "done": step_done,
}.get(bk.get("step"), step_search)()
