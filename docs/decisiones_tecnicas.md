# Decisiones técnicas — Pipeline ETL DataMart S.A.S.

> Todas las cifras de este documento salen de correr el pipeline completo
> y las consultas de `include/sql/business_questions.sql`.

## 1. Arquitectura

```text
 data.csv ──────────┐                                   ┌─> dim_product
                    ├─ extract ─> transform ─> quality ─> load ─┼─> fact_transactions ─> fact_daily_product_revenue
 online_retail.csv ─┘   (work/raw_*.csv)  (work/*.csv)          ├─> etl_rejections
                                                                └─> etl_source_summary
```

- **Docker Compose** levanta Airflow 3.1 (api-server, scheduler, dag-processor, triggerer) y **dos PostgreSQL**: uno para los metadatos de Airflow y otro para el Data Warehouse. Así, los datos del negocio no se mezclan con los de la herramienta.
- **El DAG solo orquesta.** La lógica está en `include/datamart_etl/` (un archivo por etapa), y esas funciones no importan Airflow, así que se pueden probar solas.
- **Las tareas se pasan los datos por archivos CSV** en `data/work/` y no por XCom, porque XCom se guarda en la base de metadatos y no está pensado para ~1 millón de filas.
- **Todas las decisiones de negocio** (fuentes, prioridad, códigos que no son productos, categorías, motivos de rechazo) están en un solo archivo: `include/datamart_etl/config.py`. Para cambiar una decisión no hay que tocar la lógica.

## 2. Exploración de las fuentes

Script: `include/scripts/explore_data.py`.

| Hallazgo | `data.csv` | `online_retail.csv` | Decisión |
|---|---|---|---|
| Filas | 541.909 | 541.909 | — |
| Columnas | 8 | 9 (agrega `index`) | Se mapean a nombres estándar |
| Codificación | cp1252 | UTF-8 con BOM | Se lee cada una con la suya y se escribe en UTF-8 |
| `CustomerID` vacío | 135.080 (24,9 %) | 135.080 | Se conservan (ver 5.1) |
| `Description` vacía | 1.454 | 1.454 | Todas tienen precio 0, así que se rechazan por precio |
| Cantidad < 0 | 10.624 | 10.624 | Devoluciones (`RETURN`) |
| Cantidad = 0 | 0 | 0 | La regla existe (`ADJUSTMENT`) aunque hoy no aplica |
| Precio ≤ 0 | 2.517 | 2.517 | Se rechazan con motivo |
| Facturas que empiezan con `C` | 9.288 | 9.288 | Son cancelaciones y todas tienen cantidad negativa |
| Duplicados exactos | 5.268 | 5.268 | Se descartan (ver 5.3) |
| Rango de fechas | 01/12/2010 – 09/12/2011 | igual | Hora local de Reino Unido, se pasa a UTC |
| Códigos fuera del patrón de 5 dígitos | POST, DOT, M, C2, D, S, AMAZONFEE… | igual | No son productos (ver 5.4) |
| Códigos con más de una descripción | 642 | 642 | Nombre canónico (ver 5.2) |
| Formato de valores | `17850`, `18` | `17850.0`, `18.0` | Se normalizan antes de comparar |

**Hallazgo clave:** la fuente del enunciado (`online_retail_II.csv`) no estaba disponible, así que los evaluadores la reemplazaron por `online_retail.csv`. Al compararlas fila por fila, **las dos tienen exactamente los mismos registros**. Solo cambia el formato: la columna `index`, el CustomerID como decimal (`17850.0`) y 4.503 precios escritos con `.0`.

**Moneda:** las dos fuentes están en libras esterlinas (GBP), así que no hace falta convertir. Si llegara una fuente en otra moneda, habría que agregar una columna `currency` y una tabla de tasas.

## 3. Reglas de negocio aplicadas

| Regla del enunciado | Cómo se aplica | Dónde |
|---|---|---|
| Cantidad ≤ 0 = devolución o ajuste | `transaction_type` = `SALE` / `RETURN` / `ADJUSTMENT` | `transform.transaction_type_for` |
| Precio ≤ 0 se rechaza con motivo | Va a `etl_rejections` con el motivo y el valor | `transform.parse_price` |
| Fechas en UTC | Se interpretan en `SOURCE_TIMEZONE` (Europe/London) y se pasan a UTC, por lo que en horario de verano se resta 1 hora | `transform.parse_date_to_utc` |
| Códigos en mayúsculas y sin espacios | `' bank charges '` → `BANKCHARGES` | `transform.clean_stock_code` |
| Revenue bruto = cantidad × precio | `line_amount` en `fact_transactions`; `gross_revenue` en la tabla diaria | `transform.clean_row` |
| Revenue neto = bruto − devoluciones del mismo producto y día | `net_revenue` en `fact_daily_product_revenue` | `sql/refresh_daily_revenue.sql` |

## 4. Modelo del Data Warehouse

Ver el diagrama en [`diagrama_er.md`](diagrama_er.md).

Elegí un **esquema estrella sencillo**:

- **`fact_transactions`** guarda una fila por línea de factura, **con ventas y devoluciones juntas** y separadas por `transaction_type`. Las dejo en la misma tabla porque comparten exactamente las mismas columnas, y así el neto se calcula con una simple suma. Separarlas en dos tablas obligaría a hacer `UNION` en cada consulta.
- **`dim_product`** guarda un registro por código, con el nombre canónico, la categoría y `is_product`. La llave es el propio `stock_code` (llave natural), porque ya es único y estable; un ID artificial no aportaba nada.
- **`fact_daily_product_revenue`** es la tabla que pide la regla de negocio: bruto, devoluciones y neto **por producto y por día**. Las preguntas mensuales y por producto se responden sumando esta tabla.
- **`etl_rejections` y `etl_source_summary`** son de auditoría: registran qué no entró y por qué, y cuánto aportó cada fuente.
- Las **llaves foráneas son reales** (no solo conceptuales). Por eso la carga inserta primero `dim_product` y después los hechos.

## 5. Casos ambiguos

### 5.1 Transacciones sin customer ID → se conservan con `customer_id = NULL`

Son ventas reales: tienen producto, precio y fecha. Descartarlas haría que el revenue reportado no cuadrara con lo facturado.

**Impacto medido** (consultas 5 y 5B, solo productos):

| | Cliente identificado | Sin cliente |
|---|---|---|
| % del revenue de productos | 85,3 % | **14,7 %** |
| Líneas por factura | 21,3 | **95,8** |
| Ticket promedio (GBP) | 474,77 | **1.101,38** |
| Unidades por línea | 13,1 | 3,2 |
| % de devolución | 5,40 % | 0,27 % |

Las facturas sin cliente son pocas pero muy grandes (muchos productos distintos, pocas unidades de cada uno). Parecen ventas de mostrador o de un canal que no registra al cliente. Si las hubiera excluido, se perdería el 14,7 % del revenue. Como conservé el NULL en lugar de inventar un ID, cualquier análisis por cliente puede filtrarlas con `WHERE customer_id IS NOT NULL`.

### 5.2 Descripciones distintas para el mismo código → nombre canónico = la más frecuente

1. Se limpian espacios y se pasan a **mayúsculas** (así `Candle Holder White` y `CANDLE HOLDER WHITE` cuentan como la misma).
2. Se cuenta cuántas veces aparece cada versión y **gana la más frecuente**.
3. Si hay empate, gana la primera en orden alfabético, para que el resultado sea siempre el mismo.

La descripción original de cada fila se guarda en `fact_transactions.description_raw`, así que no se pierde información. De 642 códigos con descripciones distintas en la fuente, quedan **207** después de rechazar las filas con precio 0 (que traían textos como "damaged" o "?") y de unificar mayúsculas.

### 5.3 Duplicados entre fuentes → clave de negocio + prioridad de fuente

- **Clave de negocio:** factura + código + fecha UTC + cantidad + precio, calculada **después** de limpiar (así `18` y `18.0` dan la misma clave). Se guarda como hash SHA-256 en `transaction_key`, que es la llave primaria.
- **Prioridad:** si la clave ya se vio, la fila se descarta. Las fuentes se procesan en el orden de `config.SOURCES`: primero `data.csv` (el volcado diario, que es la fuente operacional) y después `online_retail.csv`.
- Con la misma regla se descartan los **duplicados exactos dentro de una misma fuente**: los trato como doble registro de la misma línea.

**Resultado** (`etl_source_summary`):

| Fuente | Leídas | Cargadas | Rechazadas | Duplicadas |
|---|---|---|---|---|
| sales (`data.csv`) | 541.909 | 534.127 | 2.517 | 5.265 |
| history (`online_retail.csv`) | 541.909 | **0** | 2.517 | 539.392 |

La segunda fuente no aporta filas nuevas, lo que confirma que es el mismo dataset. El pipeline la procesa igual: si mañana trae filas que no existen en `data.csv`, esas sí se cargan.

### 5.4 Códigos que no son productos → se cargan, pero con `is_product = FALSE`

Los códigos POST, DOT, C2 (envíos), M (ajuste manual), D (descuento), S (muestras), B (deuda incobrable), BANKCHARGES, AMAZONFEE, CRUK (comisiones) y GIFT_* (bonos de regalo) son movimientos reales de dinero, pero no son productos. No los rechazo, porque son datos válidos, pero los marco para que **no distorsionen los análisis de producto**. Por ejemplo, AMAZONFEE suma −221.520 GBP y aparecería como "el producto que más pierde".

### 5.5 Categoría de producto → palabras clave sobre el nombre canónico

No construí la API de catálogo (era opcional). La categoría se asigna buscando palabras de la descripción en listas por categoría (`config.CATEGORY_KEYWORDS`); gana la primera que coincida.

- Cubre el **~91 % del revenue**; el resto queda en "Otros".
- Es una heurística: hay errores puntuales. Cuando exista la API, se reemplaza esta función por la categoría que entregue la API, sin tocar el resto del pipeline.

## 6. Idempotencia

**Estrategia: recarga completa dentro de una transacción.**

1. `load_warehouse` hace `TRUNCATE` de las tablas y luego `COPY` de los archivos, **todo en una sola transacción**. Si algo falla, PostgreSQL hace rollback y las tablas quedan como estaban; nunca quedan a medias.
2. `refresh_daily_revenue` hace `TRUNCATE` + `INSERT ... SELECT` de la tabla diaria.
3. Además, `transaction_key` es llave primaria: aunque hubiera un error de lógica, la base no aceptaría la misma línea dos veces.
4. `max_active_runs=1` evita que dos corridas escriban al mismo tiempo.

**Prueba:** corrí la carga dos veces seguidas y obtuve los mismos conteos (534.127 transacciones, 3.828 productos, 5.034 rechazos, 278.011 filas diarias), el mismo revenue neto y el mismo hash MD5 de todas las `transaction_key`.

**¿Por qué recarga completa y no incremental?** Los archivos son volcados completos de unas 540 mil filas y la carga tarda menos de un minuto. La recarga completa es la forma más simple de garantizar que dos ejecuciones den *exactamente* el mismo resultado, incluso si cambia una regla de limpieza. Cuando el volumen crezca, el siguiente paso sería cargar por fecha (`DELETE WHERE fecha = día` + `INSERT`).

## 7. Connections, Variables y reintentos

| Elemento | Valor | Dónde se usa |
|---|---|---|
| Connection `warehouse_db` | Postgres del DW | `load_warehouse` (vía `PostgresHook`) y `refresh_daily_revenue` (vía `SQLExecuteQueryOperator`) |
| Variable `RAW_CSV_PATH` | `/opt/airflow/data` | Todas las tareas Python: dónde están los CSV y la carpeta `work/` |
| Variable `SOURCE_TIMEZONE` | `Europe/London` | `transform_transactions`: zona horaria de origen para pasar a UTC |
| Variable `MAX_REJECT_PCT` | `5` | `check_data_quality`: % máximo de rechazos permitido antes de cargar |

- Las tres se crean automáticamente con `include/scripts/init_airflow.sh`, tomando sus valores del `.env`.
- Se leen con plantillas `{{ var.value.X }}`, que se resuelven **al ejecutar la tarea**. Si se leyeran con `Variable.get()` arriba en el archivo del DAG, Airflow consultaría la base cada vez que lee el archivo.
- **Reintentos:** 2 por tarea, con 2 minutos de espera. La excepción es `check_data_quality` (`retries=0`): si los datos están mal, reintentar no los arregla.
- **Compuerta de calidad:** hoy se rechaza el 0,46 % (5.034 de 1.083.818 filas). Si se supera el 5 %, el DAG se detiene antes de cargar y el Data Warehouse conserva la última carga buena.

## 8. Recomendación al equipo de producto

**Poner un control de cantidad máxima por línea de pedido (alerta o confirmación por encima de 5.000 unidades).**

- Dos líneas explican el **51,7 % de todas las devoluciones de productos** (245.949 de 475.901 GBP):
  - `23843 PAPER CRAFT, LITTLE BIRDIE`: 80.995 unidades por 168.469,60 GBP (factura 581483, 09/12/2011), cancelada 12 minutos después (C581484).
  - `23166 MEDIUM CERAMIC TOP STORAGE JAR`: 74.215 unidades por 77.183,60 GBP (factura 541431, 18/01/2011), cancelada 16 minutos después (C541433).
- Fuera de esas dos, **ninguna línea de venta supera las 4.800 unidades**, y el 99,9 % tiene 456 o menos. Un umbral de 5.000 no afectaría ventas reales.
- Por estos errores, la tasa de devolución de productos aparece en **4,64 %**, cuando la real es **2,30 %**. Además, la categoría Papelería se ve con un 13,9 % de devoluciones y diciembre 2011 con 174 mil GBP devueltos, cuando en realidad son errores de digitación.

**Apoyo para priorizar el catálogo:** Hogar genera el **54,9 % del revenue bruto** con solo 3,9 % de devoluciones. Su producto líder, `REGENCY CAKESTAND 3 TIER`, aporta 164.459 GBP netos. Es la categoría donde conviene concentrar el inventario de temporada, ya que las ventas netas suben de 1,01 M (sep-2011) a 1,43 M GBP (nov-2011).

## 9. Limitaciones y siguientes pasos

- **Categorías:** son una heurística por palabras clave (cubre ~91 % del revenue). El siguiente paso es la API de catálogo.
- **Carga completa:** está bien para este volumen; con más datos habría que pasar a carga incremental por fecha.
- **Diciembre 2011** solo tiene datos hasta el día 9, así que no es comparable con los otros meses.
- **Devoluciones de ventas anteriores al periodo:** algunos productos tienen más devoluciones que ventas dentro de los datos (tasa > 100 %).
- **Pruebas automáticas:** las funciones de `transform.py` son puras y se pueden cubrir con `pytest`. No alcancé a incluirlas.
