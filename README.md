# 항공기 예약 시스템

2026-2학기 데이터베이스설계 · 7분반 6팀

PostgreSQL 15개 테이블 위에 Streamlit으로 화면 6개를 올린 프로젝트입니다.
ORM 없이 SQL을 직접 실행하므로, 작성한 DDL과 쿼리가 그대로 돌아갑니다.

---

## 1. 로컬에서 실행

```bash
pip install -r requirements.txt
```

**DB 준비** — PostgreSQL에 `airline_db` 를 만들고 두 파일을 순서대로 실행합니다.

```bash
createdb airline_db
psql -d airline_db -f sql/schema.sql    # 테이블 15개
psql -d airline_db -f sql/seed.sql      # 샘플 데이터
python sql/seed_demo.py                 # (선택) 데모 예약·좌석 배정 약 2만 건
```

`seed_demo.py` 는 `.streamlit/secrets.toml` 의 DB에 회원 12명과 예약·탑승객·좌석 배정·결제·마일리지 이력을 만들고,
`fare.seats_sold` 를 실제 좌석 배정 수에 맞춰 다시 계산합니다. 예약이 이미 있으면 실행하지 않습니다.

`schema.sql` 맨 위에 `DROP TABLE` 이 있어 몇 번을 돌려도 깨끗하게 다시 만들어집니다.

**접속 정보** — `.streamlit/secrets.toml.example` 을 복사해 본인 값으로 바꿉니다.

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

**실행**

```bash
streamlit run app.py
```

데모 계정은 셋입니다. 비밀번호는 모두 `1234` 입니다.

| 이메일 | 이름 | 마일리지 |
|---|---|---|
| kim@hansung.ac.kr | 김한성 | 8,080 |
| lee@example.com | 이해인 | 1,200 |
| park@example.com | 박서준 | 42,500 |

---

## 2. 팀원과 함께 쓰기

**공용 DB 서버를 두지 않습니다.** 각자 로컬에 PostgreSQL을 깔고,
`sql/` 폴더의 두 파일을 Git으로 공유합니다.

제약조건을 테스트하려면 일부러 잘못된 데이터를 넣어봐야 하는데,
공용 서버면 남의 작업을 망칩니다.

**지켜야 할 세 가지**

1. **DB를 직접 고치지 않습니다.** pgAdmin에서 컬럼을 추가하고 끝내면 남들은 모릅니다.
   반드시 `sql/schema.sql` 을 고치고 커밋하세요.
2. **스키마를 바꾸면 팀에 알립니다.** "schema.sql 다시 돌리세요" 한 줄이면 됩니다.
3. **`secrets.toml` 은 커밋하지 않습니다.** 비밀번호가 들어갑니다. `.gitignore` 에 이미 있습니다.

---

## 3. Streamlit Community Cloud 배포

팀원과 교수님이 링크로 바로 볼 수 있게 올리는 방법입니다.
로컬 PostgreSQL은 인터넷에서 접속할 수 없으므로 **클라우드 DB가 따로 필요합니다.**

### 3-1. 클라우드 DB 만들기 (Neon, 무료)

1. <https://neon.tech> 가입 (GitHub 계정으로 가능)
2. 프로젝트 생성 → 리전은 **Singapore** 가 한국에서 가장 가깝습니다
3. 대시보드의 **Connection string** 에서 host · database · user · password 를 복사
4. 로컬에서 스키마와 데이터를 밀어넣습니다

```bash
psql "postgresql://<user>:<password>@<host>/<dbname>?sslmode=require" -f sql/schema.sql
psql "postgresql://<user>:<password>@<host>/<dbname>?sslmode=require" -f sql/seed.sql
python sql/seed_demo.py --dsn "postgresql://<user>:<password>@<host>/<dbname>?sslmode=require"
```

### 3-2. GitHub에 올리기

```bash
git init
git add .
git commit -m "Streamlit 초안"
git branch -M main
git remote add origin https://github.com/<계정>/<저장소>.git
git push -u origin main
```

`secrets.toml` 이 올라가지 않았는지 확인하세요.

```bash
git ls-files | grep secrets      # secrets.toml.example 만 나와야 정상
```

### 3-3. 배포

1. <https://share.streamlit.io> 에 GitHub 계정으로 로그인
2. **New app** → 저장소 · 브랜치(`main`) · 메인 파일(`app.py`) 선택
   - 저장소가 Private 이어도 됩니다. 로그인할 때 접근 권한을 주면 보입니다.
3. **Advanced settings → Secrets** 에 아래를 붙여넣습니다

```toml
[postgres]
host     = "ep-xxxx-xxxx.ap-southeast-1.aws.neon.tech"
port     = 5432
dbname   = "airline_db"
user     = "neondb_owner"
password = "..."
sslmode  = "require"
```

4. **Deploy** 를 누르면 몇 분 뒤 `https://<앱이름>.streamlit.app` 이 생깁니다.

이후 `main` 에 푸시하면 자동으로 다시 배포됩니다.

> 무료 플랜은 한동안 접속이 없으면 앱이 잠듭니다.
> 다시 열면 30초쯤 뒤에 깨어나므로, 발표 직전에 미리 한 번 열어두세요.

---

## 4. 구조

```
app.py                    진입점 · 로그인 상태별 메뉴 (고객: 상단 / 관리자: 사이드바)
db.py                     DB 연결, 로그인·회원가입, 관리자 로그인, 트랜잭션 헬퍼
services.py               여러 테이블을 함께 바꾸는 업무 처리 (예약 · 취소 · 체크인 · 운항 완료 · 소멸)
booking_view.py           예약 상세 화면 조각 (고객 예약 조회 · 관리자 예약 관리 공용)
ui.py                     스타일 · 한글 라벨 · 카드/배지/좌석 배치도 조각
views/
  search.py               항공편 검색 → 결과 → 좌석 선택 → 예약 정보·결제 → 완료
  lookup.py               예약번호 + 영문 성 조회 · 구간 단위 취소
  checkin.py              온라인 체크인 3단계 · 탑승권
  mileage.py              잔액 · 등급 · 적립/사용 내역        (회원)
  mypage.py               회원 정보 · 내 예약 목록           (회원)
  login.py · signup.py    로그인(회원/관리자) · 회원가입
  admin/
    dashboard.py          예약 수 · 매출 · 탑승률 · 등급 분포
    flights.py            편명(flight) 등록 · 수정 · 삭제
    schedules.py          날짜별 운항 · 상태/탑승구 · 탑승 처리 · 운항 완료(마일리지 적립)
    aircraft.py           기종 · 좌석 배치도 · 항공기 등록
    bookings.py           예약 검색 · 상세 · 취소
    members.py            회원 목록 · 등급 변경 · 만료 마일리지 소멸
sql/
  schema.sql              DDL · 제약조건 · 인덱스
  seed.sql                샘플 데이터 (운항 410편, 운임 1,640건)
  seed_demo.py            데모 예약 데이터 생성 (선택)
```

**관리자 계정**은 DB가 아니라 `secrets.toml` 의 `[admin]` 에서 읽습니다
(`secrets.toml.example` 참고). Streamlit Cloud 에서는 Settings → Secrets 에 같은 내용을 넣습니다.

| 담당 | 파일 |
|---|---|
| 정래원 | `db.py` `app.py` `views/search.py` `views/admin/*` |
| 이해인 | `views/lookup.py` `views/checkin.py` `views/mileage.py` |

새로 생긴 `services.py` `booking_view.py` `ui.py` `views/mypage.py` `views/login.py` `views/signup.py` 는 담당을 정해야 합니다.

---

## 5. 로그인과 회원 · 비회원

로그인은 **별도 화면이 아니라 사이드바**에 있습니다. 화면 수는 6개 그대로입니다.

로그인 여부가 회원 예약과 비회원 예약을 가릅니다.

| 화면 | 회원 | 비회원 |
|---|---|---|
| 항공편 검색 | 동일 | 동일 (로그인 불필요) |
| 예약하기 | 예약자 자동 지정 | `BOOKING.member_id` 가 NULL |
| 예약 조회 | 계정으로 내 예약 전부 | 예약번호 + 탑승객 영문 성 |
| 마일리지 | 잔액 · 이력 | 접근 불가 (계좌가 없음) |

비밀번호는 `pbkdf2_sha256` 으로 해시해 저장하며 평문은 남기지 않습니다.

---

## 6. 아직 안 한 것

- 경유(환승) 예약은 아직 없습니다. 편도·왕복만 지원합니다.
- `seed.sql` 에서 B737-800(비즈니스석 0석, 이코노미석 150석)에도 비즈니스 운임(C) 8석과
  이코노미 운임 합계 180석이 잡혀 있습니다. 실제 좌석 수와 맞지 않아 `seed_demo.py` 는
  B737 비즈니스석을 팔지 않습니다.
- 지연 시각을 저장할 컬럼이 없습니다. `flight_status` 로 지연 여부만 관리합니다.
- 좌석이 그 운항편의 기종에 속하는지는 외래키로 보장되지 않아,
  애플리케이션에서 검증합니다.
