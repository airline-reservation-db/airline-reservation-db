"""
DB 연결, 로그인, 공통 쿼리 헬퍼.

모든 페이지가 이 모듈만 통해 DB에 접근한다.
접속 정보는 .streamlit/secrets.toml 의 [postgres] 에서 읽는다.
"""
import base64
import hashlib
import hmac
import os
import secrets as pysecrets
import time
from contextlib import contextmanager

import pandas as pd
import psycopg2
import psycopg2.extras
import psycopg2.pool
import streamlit as st

# ---------------------------------------------------------------- 연결

DEFAULT = {
    "host": "localhost",
    "port": 5432,
    "dbname": "airline_db",
    "user": "postgres",
    "password": "postgres",
}


def _config() -> dict:
    """secrets.toml → 환경변수 → 기본값 순으로 접속 정보를 찾는다."""
    try:
        cfg = dict(st.secrets["postgres"])
    except Exception:
        cfg = dict(DEFAULT)
        url = os.environ.get("DATABASE_URL")
        if url:
            return {"dsn": url}
    cfg.setdefault("connect_timeout", 10)
    return cfg


@st.cache_resource
def _pool() -> psycopg2.pool.ThreadedConnectionPool:
    """
    앱 전체가 공유하는 커넥션 풀.

    예전에는 연결 하나를 모든 사용자가 같이 써서, 동시에 접속하면
    한 사람의 롤백이 다른 사람의 작업까지 되돌릴 수 있었다.
    이제는 요청마다 풀에서 연결을 빌려 쓰고 돌려준다.
    """
    cfg = _config()
    # TCP keepalive: 클라우드 DB나 중간 장비가 조용히 끊은 연결을 빨리 알아챈다
    alive = {"keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3}
    if "dsn" in cfg:
        return psycopg2.pool.ThreadedConnectionPool(1, 10, cfg["dsn"], **alive)
    return psycopg2.pool.ThreadedConnectionPool(1, 10, **cfg, **alive)


_last_used: dict[int, float] = {}   # id(conn) -> 마지막 반납 시각
IDLE_CHECK = 60                      # 이만큼(초) 쉰 연결은 쓰기 전에 살아있는지 확인


def _alive(conn) -> bool:
    if conn.closed:
        return False
    if time.monotonic() - _last_used.get(id(conn), 0) < IDLE_CHECK:
        return True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.rollback()
        return True
    except psycopg2.Error:
        return False


@contextmanager
def get_conn():
    """
    풀에서 연결 하나를 빌린다. 블록이 끝나면 반납한다.

        with get_conn() as conn:
            ...

    클라우드 DB(Neon)는 오래 쉰 연결을 끊으므로, 끊긴 연결은 버리고 새로 받는다.
    """
    pool = _pool()
    conn = pool.getconn()
    for _ in range(10):
        if _alive(conn):
            break
        _last_used.pop(id(conn), None)
        pool.putconn(conn, close=True)
        conn = pool.getconn()
    conn.autocommit = False
    try:
        yield conn
    finally:
        broken = conn.closed != 0
        if not broken:
            try:
                conn.rollback()  # 커밋 안 된 작업이 남아 있으면 다음 사용자에게 넘기지 않는다
            except psycopg2.Error:
                broken = True
        if broken:
            _last_used.pop(id(conn), None)
        else:
            _last_used[id(conn)] = time.monotonic()
        pool.putconn(conn, close=broken)


def q(sql: str, params=None) -> pd.DataFrame:
    """SELECT 실행 후 DataFrame 반환."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            rows = cur.fetchall()
        conn.commit()
        return pd.DataFrame(rows)


def q1(sql: str, params=None):
    """단일 값 조회. 결과가 없으면 None."""
    df = q(sql, params)
    return None if df.empty else df.iloc[0, 0]


def execute(sql: str, params=None, returning: bool = False):
    """INSERT / UPDATE 단건 실행. returning=True면 RETURNING 값을 돌려준다."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            out = cur.fetchone()[0] if returning else cur.rowcount
        conn.commit()
        return out


class tx:
    """
    여러 문장을 하나의 트랜잭션으로 묶는다.

        with tx() as cur:
            cur.execute(...)
            cur.execute(...)

    블록 안에서 예외가 나면 전부 롤백된다.
    예약 생성, 결제, 마일리지 차감처럼 중간에 끊기면 안 되는 작업에 쓴다.
    """

    def __enter__(self):
        self._lease = get_conn()
        self.conn = self._lease.__enter__()
        self.cur = self.conn.cursor()
        return self.cur

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
            self.cur.close()
        finally:
            self._lease.__exit__(exc_type, exc, tb)
        return False


# ---------------------------------------------------------------- 비밀번호

ITERATIONS = 120_000


def hash_password(plain: str) -> str:
    """pbkdf2_sha256$반복수$솔트$해시 형식으로 저장한다."""
    salt = pysecrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(dk).decode(),
    )


def verify_password(plain: str, stored: str) -> bool:
    """저장된 해시와 입력값을 비교한다. 평문은 어디에도 남기지 않는다."""
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", plain.encode(), base64.b64decode(salt_b64), int(iters)
        )
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except Exception:
        return False


# ---------------------------------------------------------------- 로그인

def login(email: str, password: str):
    """성공하면 회원 정보를 세션에 담고 True를 돌려준다."""
    row = q(
        "SELECT member_id, member_name, password FROM member WHERE email = %s",
        (email.strip(),),
    )
    if row.empty:
        return False
    r = row.iloc[0]
    if not verify_password(password, r.password):
        return False
    st.session_state.pop("admin", None)
    st.session_state["member"] = {
        "member_id": int(r.member_id),
        "member_name": r.member_name,
        "email": email.strip(),
    }
    return True


def logout():
    for k in list(st.session_state.keys()):
        del st.session_state[k]


def current_member():
    """로그인한 회원 정보. 비로그인이면 None."""
    return st.session_state.get("member")


def require_login(message: str = "로그인이 필요한 화면입니다."):
    """로그인이 반드시 필요한 화면에서 호출한다."""
    m = current_member()
    if not m:
        st.info(message)
        if st.button("로그인하러 가기", type="primary"):
            st.switch_page("views/login.py")
        st.stop()
    return m


def email_taken(email: str) -> bool:
    return q1("SELECT count(*) FROM member WHERE lower(email) = lower(%s)", (email.strip(),)) > 0


def signup(name: str, email: str, phone: str, password: str) -> int:
    """
    회원과 마일리지 계좌를 한 트랜잭션으로 만든다.
    계좌는 회원당 1개(mileage_account.member_id UNIQUE)라 가입 시점에 함께 연다.
    """
    with tx() as cur:
        cur.execute(
            """INSERT INTO member (email, password, member_name, phone)
               VALUES (%s, %s, %s, NULLIF(%s, ''))
               RETURNING member_id""",
            (email.strip(), hash_password(password), name.strip(), phone.strip()),
        )
        member_id = cur.fetchone()[0]
        cur.execute("INSERT INTO mileage_account (member_id) VALUES (%s)", (member_id,))
    st.session_state["member"] = {
        "member_id": member_id, "member_name": name.strip(), "email": email.strip(),
    }
    return member_id


# ---------------------------------------------------------------- 관리자

def admin_configured() -> bool:
    try:
        return bool(st.secrets["admin"]["username"] and st.secrets["admin"]["password"])
    except Exception:
        return False


def admin_login(username: str, password: str) -> bool:
    """
    관리자 계정은 DB가 아니라 secrets 의 [admin] 에 둔다.
    스키마에 관리자 구분이 없어서, 데모용으로 한 계정만 허용한다.
    """
    if not admin_configured():
        return False
    a = st.secrets["admin"]
    ok_user = hmac.compare_digest(username.strip(), str(a["username"]))
    ok_pw = hmac.compare_digest(password, str(a["password"]))
    if ok_user and ok_pw:
        st.session_state.pop("member", None)
        st.session_state["admin"] = str(a["username"])
        return True
    return False


def current_admin():
    return st.session_state.get("admin")


# ---------------------------------------------------------------- 공통 조회

def airports() -> pd.DataFrame:
    return q("SELECT airport_code, airport_name, city FROM airport ORDER BY city")


def airport_options() -> dict:
    """셀렉트박스용 {표시문자열: 공항코드}"""
    df = airports()
    return {f"{r.city} ({r.airport_code})": r.airport_code for r in df.itertuples()}


def members() -> pd.DataFrame:
    return q("SELECT member_id, member_name, email FROM member ORDER BY member_id")


def won(v) -> str:
    """금액 표시."""
    return "-" if v is None else f"{int(v):,}원"


def new_pnr() -> str:
    """6자리 예약번호 생성. 중복되면 다시 뽑는다."""
    import random
    import string

    chars = string.ascii_uppercase + string.digits
    for _ in range(20):
        pnr = "".join(random.choices(chars, k=6))
        if q1("SELECT count(*) FROM booking WHERE booking_pnr = %s", (pnr,)) == 0:
            return pnr
    raise RuntimeError("예약번호를 생성하지 못했습니다")
