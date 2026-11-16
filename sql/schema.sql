-- ============================================================
-- 항공기 예약 시스템 데이터베이스
-- PostgreSQL 기준 DDL (15 테이블)
-- 2026-2학기 데이터베이스설계 / 7분반 6팀
-- ============================================================

-- 재실행을 위한 초기화 (개발 중에만 사용)
DROP TABLE IF EXISTS mileage_history   CASCADE;
DROP TABLE IF EXISTS mileage_account   CASCADE;
DROP TABLE IF EXISTS payment           CASCADE;
DROP TABLE IF EXISTS seat_assignment   CASCADE;
DROP TABLE IF EXISTS booking_segment   CASCADE;
DROP TABLE IF EXISTS passenger         CASCADE;
DROP TABLE IF EXISTS booking           CASCADE;
DROP TABLE IF EXISTS member            CASCADE;
DROP TABLE IF EXISTS fare              CASCADE;
DROP TABLE IF EXISTS flight_schedule   CASCADE;
DROP TABLE IF EXISTS flight            CASCADE;
DROP TABLE IF EXISTS seat              CASCADE;
DROP TABLE IF EXISTS aircraft          CASCADE;
DROP TABLE IF EXISTS route             CASCADE;
DROP TABLE IF EXISTS airport           CASCADE;


-- ============================================================
-- 1. 기준정보
-- ============================================================

-- 1-1. 공항
-- PK: IATA 3자리 코드. 전 세계 유일하고 변하지 않는 자연키
CREATE TABLE airport (
    airport_code    CHAR(3)       PRIMARY KEY,
    airport_name    VARCHAR(100)  NOT NULL,
    city            VARCHAR(50)   NOT NULL,
    country         VARCHAR(50)   NOT NULL
);

COMMENT ON TABLE  airport IS '공항 기준정보';
COMMENT ON COLUMN airport.airport_code IS 'IATA 3자리 코드 (ICN, GMP, JFK)';


-- 1-2. 노선
-- 거리를 노선에 두어 편명마다 중복 저장되는 것을 방지 (3NF)
CREATE TABLE route (
    route_id          SERIAL        PRIMARY KEY,
    dep_airport_code  CHAR(3)       NOT NULL REFERENCES airport(airport_code),
    arr_airport_code  CHAR(3)       NOT NULL REFERENCES airport(airport_code),
    distance_km       INT           NOT NULL,
    flight_duration   INT           NOT NULL,

    CONSTRAINT uq_route            UNIQUE (dep_airport_code, arr_airport_code),
    CONSTRAINT ck_route_diff       CHECK  (dep_airport_code <> arr_airport_code),
    CONSTRAINT ck_route_distance   CHECK  (distance_km > 0)
);

COMMENT ON COLUMN route.distance_km     IS '비행 거리. 마일리지 적립 기준값';
COMMENT ON COLUMN route.flight_duration IS '예상 소요시간(분)';


-- 1-3. 기종
CREATE TABLE aircraft (
    aircraft_id   SERIAL        PRIMARY KEY,
    model_name    VARCHAR(50)   NOT NULL,
    manufacturer  VARCHAR(50)
);

COMMENT ON TABLE aircraft IS '기종 정보. 개별 기체가 아닌 모델 단위';


-- 1-4. 좌석 배치도
-- 기종의 물리적 좌석 구조. 실제 배정은 seat_assignment
CREATE TABLE seat (
    seat_id       SERIAL        PRIMARY KEY,
    aircraft_id   INT           NOT NULL REFERENCES aircraft(aircraft_id),
    seat_number   VARCHAR(5)    NOT NULL,
    seat_class    VARCHAR(10)   NOT NULL,

    CONSTRAINT uq_seat       UNIQUE (aircraft_id, seat_number),
    CONSTRAINT ck_seat_class CHECK  (seat_class IN ('ECONOMY','BUSINESS','FIRST'))
);

COMMENT ON TABLE seat IS '기종별 좌석 배치도. 같은 기종 내 좌석번호는 유일';


-- ============================================================
-- 2. 운항
-- ============================================================

-- 2-1. 항공편 (편명)
-- 날짜 개념이 없는 정기 스케줄. 날짜별 실체는 flight_schedule
CREATE TABLE flight (
    flight_number  VARCHAR(10)  PRIMARY KEY,
    route_id       INT          NOT NULL REFERENCES route(route_id),
    std_dep_time   TIME         NOT NULL,
    std_arr_time   TIME         NOT NULL
);

COMMENT ON TABLE  flight IS '항공편 편명. 반복되는 정기 운항 정보';
COMMENT ON COLUMN flight.std_dep_time IS '계획 출발시각. 날짜 없이 시각만';


-- 2-2. 운항 스케줄 (날짜별 실체)
-- 좌석 재고, 운항 상태, 게이트 등 변하는 모든 것이 여기 귀속
CREATE TABLE flight_schedule (
    schedule_id     SERIAL        PRIMARY KEY,
    flight_number   VARCHAR(10)   NOT NULL REFERENCES flight(flight_number),
    aircraft_id     INT           NOT NULL REFERENCES aircraft(aircraft_id),
    flight_date     DATE          NOT NULL,
    flight_status   VARCHAR(12)   NOT NULL DEFAULT 'SCHEDULED',
    terminal        VARCHAR(10),
    gate            VARCHAR(10),

    CONSTRAINT uq_schedule        UNIQUE (flight_number, flight_date),
    CONSTRAINT ck_flight_status   CHECK  (flight_status IN
                                  ('SCHEDULED','DELAYED','CANCELLED','COMPLETED'))
);

COMMENT ON TABLE  flight_schedule IS '날짜별 실제 운항. 좌석 재고와 상태가 귀속되는 실체';
COMMENT ON COLUMN flight_schedule.aircraft_id IS '날짜마다 투입 기종이 바뀔 수 있어 여기에 위치';


-- 2-3. 운임 클래스
-- 같은 좌석 등급이라도 운임에 따라 가격·환불·적립률이 다름
CREATE TABLE fare (
    fare_id           SERIAL        PRIMARY KEY,
    schedule_id       INT           NOT NULL REFERENCES flight_schedule(schedule_id),
    seat_class        VARCHAR(10)   NOT NULL,
    fare_code         CHAR(1)       NOT NULL,
    base_price        INT           NOT NULL,
    seats_allotted    INT           NOT NULL,
    seats_sold        INT           NOT NULL DEFAULT 0,
    cancellation_fee  INT           NOT NULL DEFAULT 0,
    mileage_rate      INT           NOT NULL DEFAULT 100,

    CONSTRAINT uq_fare           UNIQUE (schedule_id, fare_code),
    CONSTRAINT ck_fare_class     CHECK  (seat_class IN ('ECONOMY','BUSINESS','FIRST')),
    CONSTRAINT ck_fare_price     CHECK  (base_price >= 0),
    CONSTRAINT ck_fare_seats     CHECK  (seats_sold >= 0 AND seats_sold <= seats_allotted)
);

COMMENT ON TABLE  fare IS '운항편별 운임 등급. 날짜별 가격 차이를 표현하기 위해 schedule 참조';
COMMENT ON COLUMN fare.seats_allotted IS '이 운임에 배정된 좌석 수';
COMMENT ON COLUMN fare.seats_sold     IS '판매 좌석 수. 잔여석 = allotted - sold';
COMMENT ON COLUMN fare.mileage_rate   IS '마일리지 적립률(%)';


-- ============================================================
-- 3. 회원 · 마일리지
-- ============================================================

-- 3-1. 회원
-- PK는 대리키. email은 변경 가능하므로 UNIQUE 제약만 적용
CREATE TABLE member (
    member_id     SERIAL        PRIMARY KEY,
    email         VARCHAR(100)  NOT NULL UNIQUE,
    password      VARCHAR(255)  NOT NULL,
    member_name   VARCHAR(50)   NOT NULL,
    phone         VARCHAR(20),
    join_date     TIMESTAMP     NOT NULL DEFAULT NOW()
);

COMMENT ON COLUMN member.password IS '해시 처리된 비밀번호. 평문 저장 금지';


-- 3-2. 마일리지 계좌
-- member_id에 UNIQUE를 걸어 1:1 관계를 구현
CREATE TABLE mileage_account (
    mileage_id       SERIAL       PRIMARY KEY,
    member_id        INT          NOT NULL UNIQUE REFERENCES member(member_id),
    current_balance  INT          NOT NULL DEFAULT 0,
    tier             VARCHAR(10)  NOT NULL DEFAULT 'BRONZE',
    last_updated_at  TIMESTAMP    NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_tier     CHECK (tier IN ('BRONZE','SILVER','GOLD','PLATINUM')),
    CONSTRAINT ck_balance  CHECK (current_balance >= 0)
);

COMMENT ON COLUMN mileage_account.member_id       IS 'UNIQUE 제약으로 회원당 계좌 1개를 보장';
COMMENT ON COLUMN mileage_account.current_balance IS 'history 합산값의 캐시. 갱신은 트랜잭션으로 처리';


-- ============================================================
-- 4. 예약
-- ============================================================

-- 4-1. 예약
-- 내부 식별은 booking_id, 고객 안내는 pnr로 역할 분리
CREATE TABLE booking (
    booking_id      SERIAL        PRIMARY KEY,
    member_id       INT           REFERENCES member(member_id),
    booking_pnr     CHAR(6)       NOT NULL UNIQUE,
    booking_date    TIMESTAMP     NOT NULL DEFAULT NOW(),
    total_price     INT           NOT NULL,
    booking_status  VARCHAR(12)   NOT NULL DEFAULT 'PENDING',
    contact_email   VARCHAR(100)  NOT NULL,

    CONSTRAINT ck_booking_status CHECK (booking_status IN
                                 ('PENDING','CONFIRMED','TICKETED','CANCELLED'))
);

COMMENT ON COLUMN booking.member_id     IS 'NULL 허용. 비회원 예약을 지원';
COMMENT ON COLUMN booking.booking_pnr   IS '고객 안내용 예약번호. PK로 쓰지 않음(재사용 가능)';
COMMENT ON COLUMN booking.total_price   IS '결제 시점 금액 스냅샷. 운임 변동과 무관하게 고정';


-- 4-2. 탑승객
-- 회원(로그인 주체)과 분리. 유아는 회원가입이 불가능
CREATE TABLE passenger (
    passenger_id    SERIAL        PRIMARY KEY,
    booking_id      INT           NOT NULL REFERENCES booking(booking_id),
    member_id       INT           REFERENCES member(member_id),
    last_name       VARCHAR(50)   NOT NULL,
    first_name      VARCHAR(50)   NOT NULL,
    passport_no     VARCHAR(20),
    birth_date      DATE          NOT NULL,
    passenger_type  VARCHAR(10)   NOT NULL,

    CONSTRAINT ck_passenger_type CHECK (passenger_type IN ('ADULT','CHILD','INFANT'))
);

COMMENT ON COLUMN passenger.member_id  IS 'NULL이면 마일리지 적립 대상 아님(비회원·동반 유아)';
COMMENT ON COLUMN passenger.last_name  IS '여권 영문 성. 순서 오류 검증을 위해 이름과 분리 저장';


-- 4-3. 여정 구간
-- 예약 1건에 여러 구간. 왕복·경유 표현 및 구간별 취소의 근거
CREATE TABLE booking_segment (
    segment_id      SERIAL        PRIMARY KEY,
    booking_id      INT           NOT NULL REFERENCES booking(booking_id),
    schedule_id     INT           NOT NULL REFERENCES flight_schedule(schedule_id),
    fare_id         INT           NOT NULL REFERENCES fare(fare_id),
    segment_order   INT           NOT NULL,
    segment_status  VARCHAR(10)   NOT NULL DEFAULT 'ACTIVE',

    CONSTRAINT uq_segment_order  UNIQUE (booking_id, segment_order),
    CONSTRAINT ck_segment_status CHECK  (segment_status IN ('ACTIVE','CANCELLED','FLOWN')),
    CONSTRAINT ck_segment_order  CHECK  (segment_order > 0)
);

COMMENT ON TABLE  booking_segment IS '예약-운항편 M:N을 해소하는 연결 엔티티';
COMMENT ON COLUMN booking_segment.segment_order  IS '여정 내 순서. 경유 구간의 선후 관계';
COMMENT ON COLUMN booking_segment.segment_status IS '구간 단위 부분 취소를 지원';
COMMENT ON COLUMN booking_segment.fare_id        IS '구간마다 운임이 다를 수 있어 구간에 기록';


-- 4-4. 좌석 배정
-- 두 개의 UNIQUE 제약이 좌석 중복 배정을 DB 레벨에서 차단
CREATE TABLE seat_assignment (
    seat_assign_id  SERIAL      PRIMARY KEY,
    segment_id      INT         NOT NULL REFERENCES booking_segment(segment_id),
    passenger_id    INT         NOT NULL REFERENCES passenger(passenger_id),
    seat_id         INT         NOT NULL REFERENCES seat(seat_id),
    assigned_at     TIMESTAMP   NOT NULL DEFAULT NOW(),
    checked_in_at   TIMESTAMP,
    is_boarded      BOOLEAN     NOT NULL DEFAULT FALSE,

    CONSTRAINT uq_segment_passenger UNIQUE (segment_id, passenger_id),
    CONSTRAINT uq_segment_seat      UNIQUE (segment_id, seat_id)
);

COMMENT ON CONSTRAINT uq_segment_passenger ON seat_assignment
    IS '한 구간에서 한 승객은 좌석 1개';
COMMENT ON CONSTRAINT uq_segment_seat ON seat_assignment
    IS '한 구간에서 한 좌석에는 1명. 동시 예약 시 좌석 충돌을 차단';
COMMENT ON COLUMN seat_assignment.is_boarded
    IS '실제 탑승 여부. 마일리지 적립의 최종 근거';


-- 4-5. 결제
-- booking 1 : N payment. 카드+마일리지 복합 결제를 지원
CREATE TABLE payment (
    payment_id      SERIAL        PRIMARY KEY,
    booking_id      INT           NOT NULL REFERENCES booking(booking_id),
    payment_method  VARCHAR(10)   NOT NULL,
    amount          INT           NOT NULL,
    payment_date    TIMESTAMP     NOT NULL DEFAULT NOW(),
    payment_status  VARCHAR(12)   NOT NULL DEFAULT 'COMPLETED',
    approval_no     VARCHAR(50),
    refund_amount   INT           NOT NULL DEFAULT 0,

    CONSTRAINT ck_pay_method CHECK (payment_method IN ('CARD','BANK','MILEAGE','EASY_PAY')),
    CONSTRAINT ck_pay_status CHECK (payment_status IN ('COMPLETED','FAILED','REFUNDED')),
    CONSTRAINT ck_pay_amount CHECK (amount >= 0 AND refund_amount >= 0)
);

COMMENT ON TABLE  payment IS '예약당 여러 건 가능. 복합 결제·재시도·부분 환불 이력';
COMMENT ON COLUMN payment.approval_no IS '카드 승인번호. 마일리지 결제 시 NULL';


-- ============================================================
-- 5. 마일리지 이력
--    (booking_segment·payment 참조 때문에 예약 테이블 뒤에 생성)
-- ============================================================

-- 적립 건별로 만료일과 잔여량을 관리하여 선입선출 차감을 구현
-- 적립(EARN)은 탑승 구간을, 사용(USE)은 결제 건을 근거로 가짐
CREATE TABLE mileage_history (
    history_id        SERIAL        PRIMARY KEY,
    mileage_id        INT           NOT NULL REFERENCES mileage_account(mileage_id),
    segment_id        INT           REFERENCES booking_segment(segment_id),
    payment_id        INT           REFERENCES payment(payment_id),
    change_type       VARCHAR(10)   NOT NULL,
    amount            INT           NOT NULL,
    remaining_amount  INT           NOT NULL DEFAULT 0,
    change_date       TIMESTAMP     NOT NULL DEFAULT NOW(),
    expire_at         DATE,
    reason            VARCHAR(200),

    CONSTRAINT ck_change_type CHECK (change_type IN ('EARN','USE','EXPIRE')),
    CONSTRAINT ck_mh_amount   CHECK (amount > 0),
    CONSTRAINT ck_mh_remain   CHECK (remaining_amount >= 0),
    -- 적립 건만 만료일과 잔여량을 가짐
    CONSTRAINT ck_mh_earn     CHECK (
        (change_type = 'EARN' AND expire_at IS NOT NULL)
        OR (change_type <> 'EARN' AND remaining_amount = 0)
    ),
    -- 적립은 탑승 구간에서, 사용은 결제 건에서 발생
    -- (적립 행이 결제를, 사용 행이 구간을 참조하는 일은 없음)
    CONSTRAINT ck_mh_source   CHECK (
        (change_type = 'EARN'   AND payment_id IS NULL)
        OR (change_type = 'USE' AND segment_id IS NULL)
        OR (change_type = 'EXPIRE' AND segment_id IS NULL AND payment_id IS NULL)
    )
);

COMMENT ON TABLE  mileage_history IS '마일리지 원장. account의 잔액은 이 테이블의 파생값';
COMMENT ON COLUMN mileage_history.remaining_amount IS '해당 적립 건의 잔여량. 선입선출 차감에 사용';
COMMENT ON COLUMN mileage_history.expire_at        IS '만료 예정일. EARN 행만 값을 가짐';
COMMENT ON COLUMN mileage_history.segment_id       IS '적립 근거가 된 탑승 구간. EARN만 값을 가지며 프로모션 적립은 NULL';
COMMENT ON COLUMN mileage_history.payment_id       IS '마일리지를 사용한 결제 건. USE만 값을 가짐';
COMMENT ON COLUMN mileage_history.amount           IS '항상 양수. 방향은 change_type으로 판단';


-- ============================================================
-- 6. 인덱스
--    FK와 자주 쓰는 조회 조건에 인덱스 추가
-- ============================================================

CREATE INDEX idx_route_dep        ON route(dep_airport_code);
CREATE INDEX idx_route_arr        ON route(arr_airport_code);
CREATE INDEX idx_seat_aircraft    ON seat(aircraft_id);
CREATE INDEX idx_flight_route     ON flight(route_id);
CREATE INDEX idx_schedule_date    ON flight_schedule(flight_date);
CREATE INDEX idx_schedule_flight  ON flight_schedule(flight_number);
CREATE INDEX idx_fare_schedule    ON fare(schedule_id);
CREATE INDEX idx_booking_member   ON booking(member_id);
CREATE INDEX idx_passenger_book   ON passenger(booking_id);
CREATE INDEX idx_segment_booking  ON booking_segment(booking_id);
CREATE INDEX idx_segment_schedule ON booking_segment(schedule_id);
CREATE INDEX idx_assign_segment   ON seat_assignment(segment_id);
CREATE INDEX idx_payment_booking  ON payment(booking_id);
CREATE INDEX idx_mh_account       ON mileage_history(mileage_id);
CREATE INDEX idx_mh_segment       ON mileage_history(segment_id);
CREATE INDEX idx_mh_payment       ON mileage_history(payment_id);

-- 만료 예정 마일리지 조회용 부분 인덱스
CREATE INDEX idx_mh_expire ON mileage_history(mileage_id, expire_at)
    WHERE change_type = 'EARN' AND remaining_amount > 0;