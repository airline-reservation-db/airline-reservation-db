"""
데모용 예약 데이터 생성기.

seed.sql 은 운임별 seats_sold 숫자만 넣고 실제 예약은 비워 둔다.
그러면 좌석 배치도가 텅 비어 보이므로, 이 스크립트가
  회원 · 예약 · 탑승객 · 구간 · 좌석 배정 · 결제 · 마일리지 이력
을 만들고 seats_sold 를 실제 배정 수에 맞춰 다시 계산한다.

  python sql/seed_demo.py            # .streamlit/secrets.toml 의 [postgres] 로 접속
  python sql/seed_demo.py --dsn ...  # 직접 지정

예약이 이미 있으면 아무것도 하지 않는다. 전체가 하나의 트랜잭션이다.
"""
import argparse
import base64
import datetime as dt
import hashlib
import random
import re
import secrets
import string
import tomllib
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extras import execute_values

random.seed(20261119)
KST = ZoneInfo("Asia/Seoul")
NOW = dt.datetime.now(KST).replace(tzinfo=None)
TODAY = NOW.date()
MILE_WON, INFANT_RATE, EARN_YEARS = 10, 0.1, 10

LAST = [("김", "KIM"), ("이", "LEE"), ("박", "PARK"), ("최", "CHOI"), ("정", "JUNG"), ("강", "KANG"),
        ("조", "CHO"), ("윤", "YOON"), ("장", "JANG"), ("임", "LIM"), ("한", "HAN"), ("오", "OH"),
        ("서", "SEO"), ("신", "SHIN"), ("권", "KWON"), ("황", "HWANG"), ("송", "SONG"), ("류", "RYU")]
FIRST = [("민준", "MINJUN"), ("서연", "SEOYEON"), ("도윤", "DOYUN"), ("지우", "JIWOO"), ("하준", "HAJUN"),
         ("서윤", "SEOYUN"), ("지호", "JIHO"), ("하은", "HAEUN"), ("예준", "YEJUN"), ("수아", "SUA"),
         ("시우", "SIWOO"), ("지아", "JIA"), ("주원", "JUWON"), ("채원", "CHAEWON"), ("현우", "HYUNWOO"),
         ("다은", "DAEUN"), ("건우", "GUNWOO"), ("유진", "YUJIN"), ("우진", "WOOJIN"), ("소윤", "SOYUN"),
         ("민서", "MINSEO"), ("태윤", "TAEYUN"), ("은우", "EUNWOO"), ("지민", "JIMIN")]


def hash_pw(plain):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, 120000)
    return f"pbkdf2_sha256$120000${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def rand_birth(kind, flight_date):
    if kind == "INFANT":
        return flight_date - dt.timedelta(days=random.randint(40, 680))
    if kind == "CHILD":
        return flight_date - dt.timedelta(days=random.randint(3 * 365, 11 * 365))
    return dt.date(random.randint(1958, 2004), random.randint(1, 12), random.randint(1, 28))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dsn = args.dsn or tomllib.loads(
        (Path(__file__).resolve().parent.parent / ".streamlit/secrets.toml").read_text()
    )["postgres"]["dsn"]
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()

    cur.execute("SELECT count(*) FROM booking")
    if cur.fetchone()[0]:
        print("booking 테이블에 이미 데이터가 있어 중단합니다.")
        return

    # ------------------------------------------------------------ 기준 데이터
    cur.execute("""SELECT fs.schedule_id, fs.flight_date, fs.flight_status, fs.aircraft_id,
                          f.flight_number, f.std_dep_time, r.distance_km
                   FROM flight_schedule fs JOIN flight f USING (flight_number) JOIN route r USING (route_id)
                   ORDER BY fs.flight_date, f.std_dep_time""")
    scheds = [dict(zip(["id", "date", "status", "ac", "no", "dep", "dist"], r)) for r in cur.fetchall()]
    sched_by_id = {s["id"]: s for s in scheds}

    cur.execute("SELECT fare_id, schedule_id, seat_class, fare_code, base_price, seats_allotted, "
                "cancellation_fee, mileage_rate FROM fare")
    fares = {}
    for fid, sid, cls, code, price, allot, fee, rate in cur.fetchall():
        fares[(sid, code)] = dict(id=fid, cls=cls, price=price, allot=allot, fee=fee, rate=rate)

    cur.execute("SELECT seat_id, aircraft_id, seat_number, seat_class FROM seat")
    ac_seats = defaultdict(list)
    for sid, ac, no, cls in cur.fetchall():
        m = re.match(r"(\d+)([A-Z])", no)
        ac_seats[(ac, cls)].append((int(m[1]), m[2], sid))
    for v in ac_seats.values():
        v.sort()

    cur.execute("SELECT m.member_id, m.member_name, m.email, ma.mileage_id FROM member m "
                "JOIN mileage_account ma USING (member_id) ORDER BY member_id")
    members = [dict(zip(["id", "name", "email", "mid"], r)) for r in cur.fetchall()]

    # ------------------------------------------------------------ 회원 추가
    pw = hash_pw("1234")
    used_names = {m["name"] for m in members}
    new_members = []
    while len(new_members) < 12:
        (lk, le), (fk, fe) = random.choice(LAST), random.choice(FIRST)
        if lk + fk in used_names:
            continue
        used_names.add(lk + fk)
        new_members.append((lk + fk, le, fe))
    for i, (name, le, fe) in enumerate(new_members, start=1):
        joined = NOW - dt.timedelta(days=random.randint(60, 1500))
        cur.execute("""INSERT INTO member (email, password, member_name, phone, join_date)
                       VALUES (%s, %s, %s, %s, %s) RETURNING member_id""",
                    (f"{fe.lower()}.{le.lower()}@example.com", pw, name,
                     f"010-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}", joined))
        mem_id = cur.fetchone()[0]
        tier = random.choice(["BRONZE", "BRONZE", "BRONZE", "SILVER", "SILVER", "GOLD", "PLATINUM"])
        cur.execute("INSERT INTO mileage_account (member_id, tier) VALUES (%s, %s) RETURNING mileage_id",
                    (mem_id, tier))
        members.append(dict(id=mem_id, name=name, email=f"{fe.lower()}.{le.lower()}@example.com",
                            mid=cur.fetchone()[0]))
    roman = {m["name"]: (le, fe) for m in members for (n, le, fe) in new_members if n == m["name"]}
    roman.update({"김한성": ("KIM", "HANSUNG"), "이해인": ("LEE", "HAEIN"), "박서준": ("PARK", "SEOJUN")})

    # ------------------------------------------------------------ id 시작값
    def next_id(table, col):
        cur.execute(f"SELECT COALESCE(MAX({col}), 0) FROM {table}")
        a = cur.fetchone()[0]
        cur.execute(f"SELECT last_value FROM {table}_{col}_seq")
        return max(a, cur.fetchone()[0]) + 1

    ids = dict(b=next_id("booking", "booking_id"), p=next_id("passenger", "passenger_id"),
               s=next_id("booking_segment", "segment_id"), a=next_id("seat_assignment", "seat_assign_id"),
               pay=next_id("payment", "payment_id"), h=next_id("mileage_history", "history_id"))

    def take(k):
        v = ids[k]
        ids[k] += 1
        return v

    rows = defaultdict(list)
    sold = defaultdict(int)
    taken = defaultdict(set)          # schedule_id -> 사용된 seat_id
    pnrs = set()
    balance = defaultdict(int)

    def pick_seats(sched, cls, k):
        seats = ac_seats[(sched["ac"], cls)]
        free = taken[sched["id"]]
        for _ in range(30):            # 같은 열에 붙어 앉히기
            i = random.randrange(len(seats))
            block = seats[i:i + k]
            if len(block) == k and len({r for r, _, _ in block}) == 1 and not any(s in free for _, _, s in block):
                break
        else:
            block = random.sample([x for x in seats if x[2] not in free], k)
        for _, _, s in block:
            free.add(s)
        return [s for _, _, s in block]

    def capacity(sched, code):
        f = fares[(sched["id"], code)]
        left_seats = len(ac_seats[(sched["ac"], f["cls"])]) - sum(
            1 for s in taken[sched["id"]] if s in {x[2] for x in ac_seats[(sched["ac"], f["cls"])]})
        return min(f["allot"] - sold[f["id"]], left_seats)

    def make_party(size, member=None):
        last_r = roman[member["name"]] if member else (None, None)
        surname = last_r[0] or random.choice(LAST)[1]
        pax = []
        for i in range(size):
            kind = "ADULT" if i == 0 or random.random() > 0.25 else "CHILD"
            first = last_r[1] if (member and i == 0) else random.choice(FIRST)[1]
            last = surname if (i == 0 or random.random() < 0.7) else random.choice(LAST)[1]
            pax.append(dict(type=kind, last=last, first=first,
                            member=member["id"] if (member and i == 0) else None))
        if size >= 2 and random.random() < 0.08:
            pax.append(dict(type="INFANT", last=surname, first=random.choice(FIRST)[1], member=None))
        return pax

    def book(segs, pax, member=None, cancel=False, cancel_full=False, use_mile=0, booked_at=None):
        """segs: [(schedule, fare_code)]"""
        first_date = sched_by_id[segs[0][0]["id"]]["date"]
        if booked_at is None:
            booked_at = dt.datetime.combine(first_date, dt.time(0)) - dt.timedelta(
                days=random.randint(2, 45), minutes=random.randint(0, 1439))
            booked_at = min(booked_at, NOW - dt.timedelta(hours=random.randint(1, 48)))
        billable = sum(p["type"] != "INFANT" for p in pax)
        infants = len(pax) - billable
        total = sum(fares[(s["id"], c)]["price"] * billable
                    + int(fares[(s["id"], c)]["price"] * INFANT_RATE) * infants for s, c in segs)
        while True:
            pnr = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if pnr not in pnrs:
                pnrs.add(pnr)
                break
        b_id = take("b")
        contact = member["email"] if member else \
            f"{pax[0]['first'].lower()}.{pax[0]['last'].lower()}{random.randint(1, 99)}@example.com"
        rows["booking"].append((b_id, member["id"] if member else None, pnr, booked_at, total,
                                "CANCELLED" if cancel else "TICKETED", contact))
        p_ids = []
        for p in pax:
            pid = take("p")
            p_ids.append(pid)
            passport = f"M{random.randint(10000000, 99999999)}" if random.random() < 0.7 else None
            rows["passenger"].append((pid, b_id, p["member"], p["last"], p["first"], passport,
                                      rand_birth(p["type"], first_date), p["type"]))

        # 결제
        cash = total - use_mile * MILE_WON
        method = random.choices(["CARD", "EASY_PAY", "BANK"], [60, 25, 15])[0]
        pay_id = None
        if use_mile:
            mp = take("pay")
            rows["payment"].append((mp, b_id, "MILEAGE", use_mile * MILE_WON, booked_at, "COMPLETED", None, 0))
            rows["history"].append((take("h"), member["mid"], None, mp, "USE", use_mile, 0, booked_at, None,
                                    f"예약 {pnr} 결제 사용"))
            balance[member["mid"]] -= use_mile
        if cash > 0:
            pay_id = take("pay")
            refund = 0
            if cancel:
                fee = 0 if cancel_full else sum(fares[(s["id"], c)]["fee"] for s, c in segs) * billable
                refund = max(0, min(cash, total - fee))
            rows["payment"].append((pay_id, b_id, method, cash, booked_at,
                                    "REFUNDED" if cancel and refund >= cash else "COMPLETED",
                                    f"A{pnr}" if method != "BANK" else None, refund))

        for order, (s, code) in enumerate(segs, start=1):
            f = fares[(s["id"], code)]
            seg_id = take("s")
            past = s["date"] < TODAY
            if cancel:
                status = "CANCELLED"
            elif s["status"] == "COMPLETED":
                status = "FLOWN"
            else:
                status = "ACTIVE"
            rows["segment"].append((seg_id, b_id, s["id"], f["id"], order, status))
            if cancel:
                continue
            sold[f["id"]] += billable
            seat_ids = pick_seats(s, f["cls"], billable)
            dep = dt.datetime.combine(s["date"], s["dep"])
            for pid, p, seat in zip([i for i, p in zip(p_ids, pax) if p["type"] != "INFANT"],
                                    [p for p in pax if p["type"] != "INFANT"], seat_ids):
                days = (s["date"] - TODAY).days
                if status == "FLOWN" or past:
                    ci = random.random() < 0.97
                    boarded = ci
                elif days == 0:
                    ci, boarded = random.random() < 0.6, False
                elif days == 1:
                    ci, boarded = random.random() < 0.25, False
                else:
                    ci, boarded = False, False
                ci_at = dep - dt.timedelta(minutes=random.randint(50, 1400)) if ci else None
                if ci_at and ci_at > NOW:
                    ci_at = NOW - dt.timedelta(minutes=random.randint(5, 300))
                rows["assign"].append((take("a"), seg_id, pid, seat, booked_at, ci_at, boarded))
                if status == "FLOWN" and boarded and p["member"]:
                    mem = next(m for m in members if m["id"] == p["member"])
                    miles = round(s["dist"] * f["rate"] / 100)
                    exp = s["date"].replace(year=s["date"].year + EARN_YEARS)
                    rows["history"].append((take("h"), mem["mid"], seg_id, None, "EARN", miles, miles,
                                            dep + dt.timedelta(hours=3), exp, f"{s['no']} 탑승 적립"))
                    balance[mem["mid"]] += miles
        return pnr

    # ------------------------------------------------------------ 데모 회원 전용 예약
    m1, m2, m3 = members[0], members[1], members[2]

    done = [s for s in scheds if s["status"] == "COMPLETED"]
    out = next(s for s in scheds if (s["date"] - TODAY).days == 6 and s["status"] == "SCHEDULED"
               and s["no"].endswith("1"))
    back = next(s for s in scheds if s["no"] == out["no"][:-1] + "2" and (s["date"] - out["date"]).days >= 3
                and s["status"] == "SCHEDULED")
    demo = []
    demo.append(book([(done[3], "M")], make_party(1, m1), member=m1))
    demo.append(book([(out, "M"), (back, "Q")], make_party(2, m1), member=m1))
    today_f = next(s for s in scheds if s["date"] == TODAY and s["status"] == "SCHEDULED")
    demo.append(book([(today_f, "Y")], make_party(1, m2), member=m2))
    later = [x for x in scheds if x["status"] == "SCHEDULED" and (x["date"] - TODAY).days >= 12]
    demo.append(book([(later[-12], "Q")], make_party(3, m2), member=m2))
    demo.append(book([(later[5], "M")], make_party(1, m2), member=m2, cancel=True))
    biz = next(s for s in scheds if s["ac"] == 1 and (s["date"] - TODAY).days == 10 and s["status"] == "SCHEDULED")
    demo.append(book([(biz, "C")], make_party(2, m3), member=m3, use_mile=5000))
    demo.append(book([(done[15], "C")], make_party(1, m3), member=m3))

    # ------------------------------------------------------------ 일반 예약 채우기
    for s in scheds:
        days = (s["date"] - TODAY).days
        if s["status"] == "CANCELLED":
            for _ in range(random.randint(8, 25)):
                book([(s, random.choice("YMQ"))], make_party(random.choice([1, 1, 2, 3])),
                     cancel=True, cancel_full=True)
            continue
        lf = (random.uniform(0.72, 0.95) if days < 0 else random.uniform(0.55, 0.85) if days <= 7
              else random.uniform(0.35, 0.6) if days <= 14 else random.uniform(0.1, 0.35))
        n_eco = len(ac_seats[(s["ac"], "ECONOMY")])
        target = {"Q": min(30, round(n_eco * lf * 0.32)), "M": min(100, round(n_eco * lf * 0.48))}
        target["Y"] = min(50, max(0, round(n_eco * lf) - target["Q"] - target["M"]))
        if ac_seats[(s["ac"], "BUSINESS")]:
            target["C"] = round(len(ac_seats[(s["ac"], "BUSINESS")]) * lf * random.uniform(0.6, 1.0))
        for code, goal in target.items():
            while True:
                room = min(goal - sold[fares[(s["id"], code)]["id"]], capacity(s, code))
                if room <= 0:
                    break
                size = min(room, random.choices([1, 2, 3, 4, 5], [45, 30, 12, 10, 3])[0])
                member = random.choice(members[3:]) if random.random() < 0.08 else None
                book([(s, code)], make_party(size, member), member=member)
            if days >= 0:                                   # 자진 취소 건
                for _ in range(random.randint(0, 2)):
                    book([(s, code)], make_party(random.choice([1, 2])), cancel=True)

    # ------------------------------------------------------------ 저장
    def put(table, cols, data):
        execute_values(cur, f"INSERT INTO {table} ({cols}) VALUES %s", data, page_size=2000)

    put("booking", "booking_id, member_id, booking_pnr, booking_date, total_price, booking_status, contact_email",
        rows["booking"])
    put("passenger", "passenger_id, booking_id, member_id, last_name, first_name, passport_no, birth_date, "
        "passenger_type", rows["passenger"])
    put("booking_segment", "segment_id, booking_id, schedule_id, fare_id, segment_order, segment_status",
        rows["segment"])
    put("seat_assignment", "seat_assign_id, segment_id, passenger_id, seat_id, assigned_at, checked_in_at, "
        "is_boarded", rows["assign"])
    put("payment", "payment_id, booking_id, payment_method, amount, payment_date, payment_status, approval_no, "
        "refund_amount", rows["payment"])

    # USE 는 기존 적립분에서 선입선출로 차감
    for h in [h for h in rows["history"] if h[4] == "USE"]:
        need = h[5]
        cur.execute("""SELECT history_id, remaining_amount FROM mileage_history
                       WHERE mileage_id = %s AND change_type = 'EARN' AND remaining_amount > 0
                       ORDER BY expire_at""", (h[1],))
        for hid, left in cur.fetchall():
            t = min(left, need)
            cur.execute("UPDATE mileage_history SET remaining_amount = remaining_amount - %s "
                        "WHERE history_id = %s", (t, hid))
            need -= t
            if need <= 0:
                break
    put("mileage_history", "history_id, mileage_id, segment_id, payment_id, change_type, amount, "
        "remaining_amount, change_date, expire_at, reason", rows["history"])
    for mid, delta in balance.items():
        cur.execute("UPDATE mileage_account SET current_balance = current_balance + %s, "
                    "last_updated_at = NOW() WHERE mileage_id = %s", (delta, mid))

    cur.execute("UPDATE fare SET seats_sold = 0")
    execute_values(cur, "UPDATE fare SET seats_sold = v.n FROM (VALUES %s) AS v(id, n) WHERE fare.fare_id = v.id",
                   list(sold.items()), page_size=2000)

    for table, col in [("booking", "booking_id"), ("passenger", "passenger_id"),
                       ("booking_segment", "segment_id"), ("seat_assignment", "seat_assign_id"),
                       ("payment", "payment_id"), ("mileage_history", "history_id")]:
        cur.execute(f"SELECT setval('{table}_{col}_seq', (SELECT MAX({col}) FROM {table}))")

    if args.dry_run:
        conn.rollback()
        print("(dry-run: 롤백함)")
    else:
        conn.commit()
    print(f"회원 +{len(new_members)}, 예약 {len(rows['booking'])}, 탑승객 {len(rows['passenger'])}, "
          f"좌석 배정 {len(rows['assign'])}, 결제 {len(rows['payment'])}, 마일리지 이력 {len(rows['history'])}")
    print("데모 회원 예약번호:", ", ".join(demo))


if __name__ == "__main__":
    main()
