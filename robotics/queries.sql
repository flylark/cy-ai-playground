-- queries.sql - SQL practice for lab.db
-- Open the database:   python -m sqlite3 lab.db
-- Then paste one query at a time. Type .quit to exit.

-- 1. See what tables exist
.tables

-- 2. All sensors
SELECT * FROM sensors;

-- 3. The 10 most recent readings
SELECT sensor_id, value, timestamp
FROM readings
ORDER BY timestamp DESC
LIMIT 10;

-- 4. Only temperature readings above 23 (WHERE filters rows)
SELECT r.sensor_id, r.value, r.timestamp
FROM readings AS r
JOIN sensors AS s ON s.sensor_id = r.sensor_id
WHERE s.sensor_type = 'temperature' AND r.value > 23;

-- 5. Count and average per sensor type (GROUP BY summarizes)
SELECT s.sensor_type, COUNT(*) AS n, ROUND(AVG(r.value), 2) AS avg_value
FROM readings AS r
JOIN sensors AS s ON s.sensor_id = r.sensor_id
GROUP BY s.sensor_type;

-- 6. Sensors that have sent more than 5 readings (HAVING filters groups)
SELECT sensor_id, COUNT(*) AS n
FROM readings
GROUP BY sensor_id
HAVING COUNT(*) > 5;

-- 7. Latest reading for each sensor
SELECT sensor_id, value, MAX(timestamp) AS latest
FROM readings
GROUP BY sensor_id;

-- 8. Only Humidity readings above 50 (WHERE filters rows)
SELECT r.sensor_id, r.value, r.timestamp
FROM readings AS r
JOIN sensors AS s ON s.sensor_id = r.sensor_id
WHERE s.sensor_type = 'humidity' AND r.value > 50;
