TRUNCATE mileage_history, mileage_account, payment, seat_assignment, booking_segment,
         passenger, booking, member, fare, flight_schedule, flight, seat, aircraft, route, airport
         RESTART IDENTITY CASCADE;

-- 공항
INSERT INTO airport VALUES
 ('ICN','인천국제공항','인천','대한민국'),
 ('GMP','김포국제공항','서울','대한민국'),
 ('CJU','제주국제공항','제주','대한민국'),
 ('PUS','김해국제공항','부산','대한민국'),
 ('FUK','후쿠오카공항','후쿠오카','일본'),
 ('NRT','나리타국제공항','도쿄','일본'),
 ('KIX','간사이국제공항','오사카','일본'),
 ('TPE','타오위안국제공항','타이베이','대만');

-- 노선 (왕복 쌍)
INSERT INTO route (dep_airport_code, arr_airport_code, distance_km, flight_duration) VALUES
 ('ICN','FUK',550,75),  ('FUK','ICN',550,75),
 ('ICN','NRT',1260,140),('NRT','ICN',1260,140),
 ('ICN','KIX',860,105), ('KIX','ICN',860,105),
 ('ICN','TPE',1480,165),('TPE','ICN',1480,165),
 ('GMP','CJU',450,70),  ('CJU','GMP',450,70);

-- 기종
INSERT INTO aircraft (model_name, manufacturer) VALUES
 ('A321-200','Airbus'), ('B737-800','Boeing');

-- 좌석: A321 비즈 8 + 이코 180, B737 이코 150
INSERT INTO seat (aircraft_id, seat_number, seat_class)
SELECT 1, r::text || c, 'BUSINESS'
FROM generate_series(1,2) r, unnest(ARRAY['A','C','D','F']) c;
INSERT INTO seat (aircraft_id, seat_number, seat_class)
SELECT 1, r::text || c, 'ECONOMY'
FROM generate_series(10,39) r, unnest(ARRAY['A','B','C','D','E','F']) c;
INSERT INTO seat (aircraft_id, seat_number, seat_class)
SELECT 2, r::text || c, 'ECONOMY'
FROM generate_series(10,34) r, unnest(ARRAY['A','B','C','D','E','F']) c;

-- 편명
INSERT INTO flight VALUES
 ('HS701', 1,'09:10','10:25'), ('HS702', 2,'13:20','15:45'),
 ('HS801', 3,'08:00','10:20'), ('HS802', 4,'11:40','14:30'),
 ('HS901', 5,'14:30','16:15'), ('HS902', 6,'17:30','19:30'),
 ('HS601', 7,'10:00','11:45'), ('HS602', 8,'13:00','16:30'),
 ('HS101', 9,'07:00','08:10'), ('HS102',10,'20:00','21:10');

-- 운항 스케줄: 오늘 기준 -10 ~ +30일
INSERT INTO flight_schedule (flight_number, aircraft_id, flight_date, flight_status, terminal, gate)
SELECT f.flight_number,
       CASE WHEN random() < 0.7 THEN 1 ELSE 2 END,
       d::date,
       CASE WHEN d::date < CURRENT_DATE THEN 'COMPLETED'
            WHEN random() < 0.04 THEN 'CANCELLED'
            WHEN random() < 0.08 THEN 'DELAYED'
            ELSE 'SCHEDULED' END,
       CASE WHEN random() < 0.5 THEN 'T1' ELSE 'T2' END,
       CASE WHEN d::date <= CURRENT_DATE + 1 THEN (100 + floor(random()*60))::text ELSE NULL END
FROM flight f,
     generate_series(CURRENT_DATE - 10, CURRENT_DATE + 30, '1 day'::interval) d;

-- 운임: 운항편마다 이코노미 3등급 + 비즈니스 1등급
INSERT INTO fare (schedule_id, seat_class, fare_code, base_price, seats_allotted, seats_sold, cancellation_fee, mileage_rate)
SELECT s.schedule_id, 'ECONOMY', 'Y',
       (r.distance_km * 420)::int, 50, floor(random()*45)::int, 0, 100
FROM flight_schedule s JOIN flight f ON s.flight_number=f.flight_number JOIN route r ON f.route_id=r.route_id;

INSERT INTO fare (schedule_id, seat_class, fare_code, base_price, seats_allotted, seats_sold, cancellation_fee, mileage_rate)
SELECT s.schedule_id, 'ECONOMY', 'M',
       (r.distance_km * 290)::int, 100, floor(random()*100)::int, 30000, 100
FROM flight_schedule s JOIN flight f ON s.flight_number=f.flight_number JOIN route r ON f.route_id=r.route_id;

INSERT INTO fare (schedule_id, seat_class, fare_code, base_price, seats_allotted, seats_sold, cancellation_fee, mileage_rate)
SELECT s.schedule_id, 'ECONOMY', 'Q',
       (r.distance_km * 180)::int, 30, 30, 80000, 50    -- 특가는 전부 매진
FROM flight_schedule s JOIN flight f ON s.flight_number=f.flight_number JOIN route r ON f.route_id=r.route_id;

INSERT INTO fare (schedule_id, seat_class, fare_code, base_price, seats_allotted, seats_sold, cancellation_fee, mileage_rate)
SELECT s.schedule_id, 'BUSINESS', 'C',
       (r.distance_km * 950)::int, 8, floor(random()*7)::int, 0, 150
FROM flight_schedule s JOIN flight f ON s.flight_number=f.flight_number JOIN route r ON f.route_id=r.route_id;

-- 회원
-- 비밀번호는 모두 1234 (데모용). pbkdf2_sha256 으로 해시하여 저장한다.
INSERT INTO member (email, password, member_name, phone) VALUES
 ('kim@hansung.ac.kr','pbkdf2_sha256$120000$/QJvCAxpp3bqivNu1I9i4g==$zmQi838xCndIovJgXg4r1BhgUn87zOO2zQ3M1lM5f0w=','김한성','010-1111-2222'),
 ('lee@example.com',  'pbkdf2_sha256$120000$kz4D/DgYcA7nmpTi1JmcYQ==$ZcIYxynIaDMWU9tjmpiuvItE4mVPVAu+HbkAQqlLaz0=','이해인','010-3333-4444'),
 ('park@example.com', 'pbkdf2_sha256$120000$6nLQG5ElCogMCSCX6OW+sA==$epHdoAtsTZ/a0uEn7thA5KutoMp2D75HEfk+Q3eUBto=','박서준','010-5555-6666');

INSERT INTO mileage_account (member_id, current_balance, tier) VALUES
 (1, 8080, 'SILVER'), (2, 1200, 'BRONZE'), (3, 42500, 'GOLD');

-- 과거 적립 이력 (선입선출 시연용)
INSERT INTO mileage_history (mileage_id, segment_id, change_type, amount, remaining_amount, change_date, expire_at, reason) VALUES
 (1, NULL, 'EARN', 2060, 2060, '2017-03-15', '2027-03-15', '과거 탑승 적립'),
 (1, NULL, 'EARN', 3000, 3000, '2021-08-02', '2031-08-02', '과거 탑승 적립'),
 (1, NULL, 'EARN', 3020, 3020, '2024-01-20', '2034-01-20', '과거 탑승 적립'),
 (3, NULL, 'EARN', 42500, 42500, '2023-05-10','2033-05-10', '과거 탑승 적립');
