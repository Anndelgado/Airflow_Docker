
-- DataMart S.A.S. - Modelo del Data Warehouse (esquema estrella)

-- Dimensión: un registro por código de producto.
CREATE TABLE IF NOT EXISTS dim_product (
    stock_code            VARCHAR(20)  PRIMARY KEY,   
    description           VARCHAR(255),               
    category              VARCHAR(50)  NOT NULL,      
    is_product            BOOLEAN      NOT NULL,      
    description_variants  INTEGER      NOT NULL       
);

-- Hecho: una fila por línea de factura (ventas Y devoluciones).
CREATE TABLE IF NOT EXISTS fact_transactions (
    transaction_key    CHAR(64)       PRIMARY KEY,    
    source             VARCHAR(20)    NOT NULL,       
    source_row_number  INTEGER        NOT NULL,      
    invoice_no         VARCHAR(20)    NOT NULL,
    stock_code         VARCHAR(20)    NOT NULL REFERENCES dim_product (stock_code),
    customer_id        VARCHAR(20),                  
    country            VARCHAR(60),
    invoice_date_utc   TIMESTAMPTZ    NOT NULL,
    quantity           INTEGER        NOT NULL,
    unit_price         NUMERIC(12, 3) NOT NULL,
    line_amount        NUMERIC(14, 2) NOT NULL,       
    transaction_type   VARCHAR(10)    NOT NULL,
    description_raw    VARCHAR(255),                  
    CONSTRAINT chk_unit_price_positive CHECK (unit_price > 0),
    CONSTRAINT chk_transaction_type CHECK (transaction_type IN ('SALE', 'RETURN', 'ADJUSTMENT'))
);

CREATE INDEX IF NOT EXISTS idx_fact_date    ON fact_transactions (invoice_date_utc);
CREATE INDEX IF NOT EXISTS idx_fact_product ON fact_transactions (stock_code);
CREATE INDEX IF NOT EXISTS idx_fact_country ON fact_transactions (country);

-- Hecho agregado: revenue bruto, devoluciones y neto por producto y día (UTC).
CREATE TABLE IF NOT EXISTS fact_daily_product_revenue (
    revenue_date     DATE           NOT NULL,
    stock_code       VARCHAR(20)    NOT NULL REFERENCES dim_product (stock_code),
    gross_revenue    NUMERIC(14, 2) NOT NULL,   
    returns_amount   NUMERIC(14, 2) NOT NULL,   
    net_revenue      NUMERIC(14, 2) NOT NULL,   
    units_sold       INTEGER        NOT NULL,
    units_returned   INTEGER        NOT NULL,
    sales_lines      INTEGER        NOT NULL,
    return_lines     INTEGER        NOT NULL,
    PRIMARY KEY (revenue_date, stock_code)
);

-- Log de rechazos: filas que no cumplieron una regla, con motivo y fuente.
CREATE TABLE IF NOT EXISTS etl_rejections (
    source             VARCHAR(20)  NOT NULL,
    source_row_number  INTEGER      NOT NULL,
    invoice_no         VARCHAR(20),
    stock_code         VARCHAR(20),
    rejection_reason   VARCHAR(100) NOT NULL,
    rejected_value     VARCHAR(100),
    rejected_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source, source_row_number)
);

-- Auditoría de la última carga: cuántas filas aportó cada fuente.
CREATE TABLE IF NOT EXISTS etl_source_summary (
    source           VARCHAR(20) PRIMARY KEY,
    priority         INTEGER     NOT NULL,
    rows_read        INTEGER     NOT NULL,
    rows_loaded      INTEGER     NOT NULL,
    rows_rejected    INTEGER     NOT NULL,
    rows_duplicated  INTEGER     NOT NULL,
    loaded_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
