# Diagrama del modelo de datos

![Modelo del Data Warehouse](diagrama_er.png)

Fuente editable del diagrama: [`modelo.mmd`](modelo.mmd) (Mermaid). GitHub también lo muestra directamente:

```mermaid
erDiagram
    DIM_PRODUCT ||--o{ FACT_TRANSACTIONS : "stock_code"
    DIM_PRODUCT ||--o{ FACT_DAILY_PRODUCT_REVENUE : "stock_code"

    DIM_PRODUCT {
        varchar stock_code PK "mayusculas, sin espacios"
        varchar description "nombre canonico"
        varchar category "por palabras clave"
        boolean is_product "FALSE = cargos y ajustes"
        int description_variants
    }
    FACT_TRANSACTIONS {
        char transaction_key PK "hash clave de negocio"
        varchar source
        int source_row_number
        varchar invoice_no
        varchar stock_code FK
        varchar customer_id "NULL = sin cliente"
        varchar country
        timestamptz invoice_date_utc
        int quantity
        numeric unit_price "mayor a 0"
        numeric line_amount "negativo si devolucion"
        varchar transaction_type "SALE RETURN ADJUSTMENT"
        varchar description_raw
    }
    FACT_DAILY_PRODUCT_REVENUE {
        date revenue_date PK
        varchar stock_code PK,FK
        numeric gross_revenue
        numeric returns_amount
        numeric net_revenue
        int units_sold
        int units_returned
        int sales_lines
        int return_lines
    }
    ETL_REJECTIONS {
        varchar source PK
        int source_row_number PK
        varchar invoice_no
        varchar stock_code
        varchar rejection_reason
        varchar rejected_value
        timestamptz rejected_at
    }
    ETL_SOURCE_SUMMARY {
        varchar source PK
        int priority
        int rows_read
        int rows_loaded
        int rows_rejected
        int rows_duplicated
        timestamptz loaded_at
    }
```

## Tablas

| Tabla | Tipo | Grano (1 fila = …) | Para qué sirve |
|---|---|---|---|
| `dim_product` | Dimensión | un código de producto | Nombre canónico, categoría y si es producto real o un cargo |
| `fact_transactions` | Hecho | una línea de factura | Detalle de ventas **y** devoluciones (`transaction_type`) |
| `fact_daily_product_revenue` | Hecho agregado | un producto en un día (UTC) | Revenue bruto, devoluciones y **neto** (regla de negocio) |
| `etl_rejections` | Auditoría | una fila rechazada | Motivo, valor rechazado y fuente de origen |
| `etl_source_summary` | Auditoría | una fuente | Filas leídas, cargadas, rechazadas y duplicadas en la última carga |

## Relaciones

- `fact_transactions.stock_code` → `dim_product.stock_code` (llave foránea real).
- `fact_daily_product_revenue.stock_code` → `dim_product.stock_code` (llave foránea real).
- Las tablas `etl_*` no se relacionan con las demás a propósito: guardan datos que **no** entraron al modelo.
