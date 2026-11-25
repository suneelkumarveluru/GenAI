-- Snowflake example with synthetic input; no objects are created or changed.
-- A production version should point to a batch-specific governed staging view.
WITH staged(order_id, line_id, amount_text, status) AS (
    SELECT * FROM VALUES
      ('A100', '1', '30.00', 'PAID'),
      ('A100', '1', '-5.00', 'UNKNOWN'),
      ('A101', '1', 'not-a-number', 'OPEN'),
      ('A102', '1', '90.00', 'PAID')
), normalized AS (
    SELECT NULLIF(TRIM(order_id), '') AS order_id,
           NULLIF(TRIM(line_id), '') AS line_id,
           TRY_TO_DECIMAL(amount_text, 18, 2) AS amount,
           TRIM(status) AS status
    FROM staged
), duplicate_groups AS (
    SELECT order_id, line_id, COUNT(*) AS row_count
    FROM normalized
    WHERE order_id IS NOT NULL AND line_id IS NOT NULL
    GROUP BY order_id, line_id
    HAVING COUNT(*) > 1
), quality_summary AS (
    SELECT COUNT(*) AS total_rows,
           COALESCE(COUNT_IF(order_id IS NULL OR line_id IS NULL), 0) AS blank_key_rows,
           COALESCE(COUNT_IF(amount IS NULL OR amount < 0 OR amount > 100000), 0) AS invalid_amount_rows,
           COALESCE(COUNT_IF(status IS NULL OR status NOT IN ('OPEN', 'PAID', 'CANCELLED')), 0)
             AS invalid_status_rows
    FROM normalized
), duplicate_summary AS (
    SELECT COALESCE(SUM(row_count - 1), 0) AS duplicate_key_rows
    FROM duplicate_groups
)
SELECT total_rows, blank_key_rows, invalid_amount_rows, invalid_status_rows, duplicate_key_rows,
       CASE WHEN total_rows > 0 AND blank_key_rows = 0 AND invalid_amount_rows = 0
          AND invalid_status_rows = 0 AND duplicate_key_rows = 0
       THEN 'PASS' ELSE 'FAIL' END AS gate_status
FROM quality_summary CROSS JOIN duplicate_summary;
-- Expected for the synthetic rows: 4 rows, 0 blanks, 2 invalid amounts,
-- 1 invalid status, 1 duplicate, FAIL.
