-- Recalcula el revenue bruto, devoluciones y neto por producto y día (UTC).
-- Se borra y se vuelve a calcular completo: correrlo dos veces da lo mismo.
-- Regla de negocio: neto = bruto - devoluciones del MISMO producto el MISMO día.

TRUNCATE fact_daily_product_revenue;

INSERT INTO fact_daily_product_revenue (
    revenue_date, stock_code,
    gross_revenue, returns_amount, net_revenue,
    units_sold, units_returned, sales_lines, return_lines
)
WITH daily AS (
    SELECT
        (invoice_date_utc AT TIME ZONE 'UTC')::DATE AS revenue_date,
        stock_code,
        SUM(CASE WHEN transaction_type = 'SALE'   THEN line_amount ELSE 0 END) AS gross_revenue,
        SUM(CASE WHEN transaction_type = 'RETURN' THEN -line_amount ELSE 0 END) AS returns_amount,
        SUM(CASE WHEN transaction_type = 'SALE'   THEN quantity ELSE 0 END) AS units_sold,
        SUM(CASE WHEN transaction_type = 'RETURN' THEN -quantity ELSE 0 END) AS units_returned,
        COUNT(*) FILTER (WHERE transaction_type = 'SALE')   AS sales_lines,
        COUNT(*) FILTER (WHERE transaction_type = 'RETURN') AS return_lines
    FROM fact_transactions
    GROUP BY 1, 2
)
SELECT
    revenue_date, stock_code,
    gross_revenue, returns_amount, gross_revenue - returns_amount AS net_revenue,
    units_sold, units_returned, sales_lines, return_lines
FROM daily;
