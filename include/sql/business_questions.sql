
-- DataMart S.A.S. - Consultas de validación / preguntas de negocio
-- Ejecutar contra el Data Warehouse después de correr el DAG.



-- 0. Validación de la carga: qué aportó cada fuente.
SELECT source, priority, rows_read, rows_loaded, rows_rejected, rows_duplicated
FROM etl_source_summary
ORDER BY priority;

SELECT source, rejection_reason, COUNT(*) AS filas
FROM etl_rejections
GROUP BY source, rejection_reason
ORDER BY source, filas DESC;


-- 1. Evolución mensual de las ventas netas (descontando devoluciones).
SELECT
    DATE_TRUNC('month', r.revenue_date)::DATE AS mes,
    ROUND(SUM(r.gross_revenue), 2)  AS revenue_bruto,
    ROUND(SUM(r.returns_amount), 2) AS devoluciones,
    ROUND(SUM(r.net_revenue), 2)    AS revenue_neto
FROM fact_daily_product_revenue r
JOIN dim_product p ON p.stock_code = r.stock_code
WHERE p.is_product
GROUP BY 1
ORDER BY 1;


-- 2. Categorías: revenue bruto y proporción de devoluciones.
SELECT
    p.category,
    ROUND(SUM(r.gross_revenue), 2)  AS revenue_bruto,
    ROUND(SUM(r.returns_amount), 2) AS devoluciones,
    ROUND(100.0 * SUM(r.returns_amount) / NULLIF(SUM(r.gross_revenue), 0), 2) AS pct_devolucion
FROM fact_daily_product_revenue r
JOIN dim_product p ON p.stock_code = r.stock_code
WHERE p.is_product
GROUP BY p.category
ORDER BY revenue_bruto DESC;


-- 3A. Top 10 productos por revenue neto.
SELECT
    p.stock_code,
    p.description,
    p.category,
    ROUND(SUM(r.gross_revenue), 2)  AS revenue_bruto,
    ROUND(SUM(r.returns_amount), 2) AS devoluciones,
    ROUND(SUM(r.net_revenue), 2)    AS revenue_neto
FROM fact_daily_product_revenue r
JOIN dim_product p ON p.stock_code = r.stock_code
WHERE p.is_product
GROUP BY p.stock_code, p.description, p.category
ORDER BY revenue_neto DESC
LIMIT 10;


-- 3B. Top 10 productos por tasa de devolución (en valor).
-- Se exige un mínimo de 1.000 de revenue bruto para no mostrar productos con una sola venta. Una tasa > 100% significa que se devolvió mercancía
-- vendida antes del inicio de los datos.
SELECT
    p.stock_code,
    p.description,
    ROUND(SUM(r.gross_revenue), 2)  AS revenue_bruto,
    ROUND(SUM(r.returns_amount), 2) AS devoluciones,
    ROUND(100.0 * SUM(r.returns_amount) / SUM(r.gross_revenue), 2) AS pct_devolucion
FROM fact_daily_product_revenue r
JOIN dim_product p ON p.stock_code = r.stock_code
WHERE p.is_product
GROUP BY p.stock_code, p.description
HAVING SUM(r.gross_revenue) >= 1000
ORDER BY pct_devolucion DESC
LIMIT 10;


-- 4. Países: transacciones y ticket promedio (solo facturas de venta).
SELECT
    country,
    COUNT(*)                   AS lineas_de_venta,
    COUNT(DISTINCT invoice_no) AS facturas,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_lineas,
    ROUND(SUM(line_amount), 2) AS revenue_bruto,
    ROUND(SUM(line_amount) / COUNT(DISTINCT invoice_no), 2) AS ticket_promedio
FROM fact_transactions
WHERE transaction_type = 'SALE'
GROUP BY country
ORDER BY lineas_de_venta DESC;


-- 5. Clientes identificados vs. transacciones sin customer ID (solo productos).
WITH ventas AS (
    SELECT
        CASE WHEN f.customer_id IS NULL THEN 'Sin cliente' ELSE 'Cliente identificado' END AS tipo,
        f.invoice_no,
        f.quantity,
        f.line_amount
    FROM fact_transactions f
    JOIN dim_product p ON p.stock_code = f.stock_code
    WHERE f.transaction_type = 'SALE' AND p.is_product
),
facturas AS (
    SELECT tipo, invoice_no, SUM(line_amount) AS total_factura, COUNT(*) AS lineas
    FROM ventas
    GROUP BY tipo, invoice_no
)
SELECT
    v.tipo,
    COUNT(*)                                                AS lineas_de_venta,
    COUNT(DISTINCT v.invoice_no)                            AS facturas,
    ROUND(100.0 * SUM(v.line_amount) / SUM(SUM(v.line_amount)) OVER (), 2) AS pct_revenue,
    ROUND(AVG(v.line_amount), 2)                            AS valor_promedio_linea,
    ROUND(AVG(v.quantity), 2)                               AS unidades_promedio_linea,
    (SELECT ROUND(AVG(f.total_factura), 2) FROM facturas f WHERE f.tipo = v.tipo) AS ticket_promedio,
    (SELECT ROUND(AVG(f.lineas), 1)        FROM facturas f WHERE f.tipo = v.tipo) AS lineas_por_factura
FROM ventas v
GROUP BY v.tipo
ORDER BY v.tipo;

-- 5B. Devoluciones según tipo de cliente (solo productos).
SELECT
    CASE WHEN f.customer_id IS NULL THEN 'Sin cliente' ELSE 'Cliente identificado' END AS tipo,
    COUNT(*) FILTER (WHERE f.transaction_type = 'RETURN') AS lineas_devolucion,
    ROUND(100.0 * SUM(-f.line_amount) FILTER (WHERE f.transaction_type = 'RETURN')
        / SUM(f.line_amount) FILTER (WHERE f.transaction_type = 'SALE'), 2) AS pct_devolucion
FROM fact_transactions f
JOIN dim_product p ON p.stock_code = f.stock_code
WHERE p.is_product
GROUP BY 1
ORDER BY 1;


-- 6A. Productos con descripción inconsistente (más de una forma de escribirse).
SELECT
    f.stock_code,
    p.description AS nombre_canonico,
    COUNT(DISTINCT f.description_raw) AS variantes,
    STRING_AGG(DISTINCT f.description_raw, ' | ') AS descripciones_encontradas
FROM fact_transactions f
JOIN dim_product p ON p.stock_code = f.stock_code
GROUP BY f.stock_code, p.description
HAVING COUNT(DISTINCT f.description_raw) > 1
ORDER BY variantes DESC, f.stock_code;

-- 6B. Total de códigos únicos (y cuántos son productos reales).
SELECT
    COUNT(*)                                   AS codigos_unicos,
    COUNT(*) FILTER (WHERE is_product)         AS productos,
    COUNT(*) FILTER (WHERE NOT is_product)     AS cargos_y_ajustes,
    COUNT(*) FILTER (WHERE description_variants > 1) AS con_descripcion_inconsistente
FROM dim_product;


-- 7. Soporte para la recomendación al equipo de producto.
-- 7A. Productos con revenue neto negativo o casi nulo pese a vender mucho.
SELECT
    p.stock_code,
    p.description,
    ROUND(SUM(r.gross_revenue), 2)  AS revenue_bruto,
    ROUND(SUM(r.returns_amount), 2) AS devoluciones,
    ROUND(SUM(r.net_revenue), 2)    AS revenue_neto
FROM fact_daily_product_revenue r
JOIN dim_product p ON p.stock_code = r.stock_code
WHERE p.is_product
GROUP BY p.stock_code, p.description
HAVING SUM(r.returns_amount) >= 1000
ORDER BY SUM(r.returns_amount) / NULLIF(SUM(r.gross_revenue), 0) DESC
LIMIT 10;

-- 7B. Peso de los cargos y ajustes (no son productos, pero afectan el neto).
SELECT
    p.stock_code,
    p.description,
    ROUND(SUM(r.net_revenue), 2) AS revenue_neto
FROM fact_daily_product_revenue r
JOIN dim_product p ON p.stock_code = r.stock_code
WHERE NOT p.is_product
GROUP BY p.stock_code, p.description
ORDER BY revenue_neto;
