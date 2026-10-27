# DataMart S.A.S. — Pipeline ETL con Apache Airflow y PostgreSQL

Pipeline diario que toma las transacciones de ventas de **dos fuentes CSV**, las limpia y aplica las reglas de negocio, separa ventas de devoluciones, registra los rechazos y carga un **Data Warehouse en PostgreSQL**. Todo está orquestado con **Apache Airflow 3.1** dentro de Docker.

-  **Modelo de datos:** [docs/diagrama_er.md](docs/diagrama_er.md)
-  **Decisiones técnicas:** [docs/decisiones_tecnicas.md](docs/decisiones_tecnicas.md)
-  **Consultas de negocio:** [include/sql/business_questions.sql](include/sql/business_questions.sql)

---

## 1. Qué levanta `docker compose up`

| Servicio | Para qué | Acceso |
|---|---|---|
| `postgres-airflow` | Metadatos internos de Airflow | interno |
| `postgres-warehouse` | **Data Warehouse** (las tablas se crean solas) | `localhost:5433` |
| `airflow-init` | Corre una vez: migra la base y crea el usuario admin, la Connection y las Variables | — |
| `airflow-apiserver` | Interfaz web de Airflow | http://localhost:8080 |
| `airflow-scheduler` | Programa y ejecuta las tareas | — |
| `airflow-dag-processor` | Lee los archivos de DAG | — |
| `airflow-triggerer` | Componente estándar de Airflow 3 | — |

No hay que entrar a la UI ni correr comandos extra para configurar nada.

## 2. Estructura del repositorio

```text
├── dags/
│   └── etl_datamart_dag.py        # Solo orquesta: tareas y dependencias
├── include/
│   ├── datamart_etl/              # Lógica del ETL (sin dependencias de Airflow)
│   │   ├── config.py              #   Decisiones de negocio: fuentes, prioridad, categorías...
│   │   ├── extract.py             #   1. Lee cada CSV y unifica columnas
│   │   ├── transform.py           #   2. Limpieza, reglas, rechazos y duplicados
│   │   ├── quality.py             #   3. Compuerta de calidad (MAX_REJECT_PCT)
│   │   └── load.py                #   4. Carga en una transacción
│   ├── sql/
│   │   ├── ddl/01_create_tables.sql   # Tablas del DW (se ejecuta al crear el contenedor)
│   │   ├── refresh_daily_revenue.sql  # 5. Revenue bruto / devoluciones / neto por día
│   │   └── business_questions.sql     # Consultas de validación (preguntas de negocio)
│   ├── scripts/
│   │   ├── init_airflow.sh        # Admin, Connection y Variables automáticas
│   │   └── explore_data.py        # Exploración de las fuentes (manual)
│   └── data/                      # data.csv y online_retail.csv (+ work/ generado)
├── docs/                          # Decisiones técnicas y diagrama
├── docker-compose.yml
├── .env.example
└── README.md
```

## 3. Requisitos

- Docker Desktop (o Docker Engine) con Docker Compose v2.
- Unos 4 GB de RAM libres para Docker.
- Git.

## 4. Levantar el entorno 

**1. Clonar el repositorio**

```bash
git clone https://github.com/Anndelgado/Airflow_Docker.git
cd Airflow_Docker
```

**2. Crear el `.env` a partir del ejemplo**

```bash
# Linux / macOS / Git Bash
cp .env.example .env
# Solo en Linux: que los contenedores escriban con tu usuario
echo "AIRFLOW_UID=$(id -u)" >> .env
```

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

**3. Levantar todo**

```bash
docker compose up -d
```

**4. Esperar a que termine la inicialización** (1–3 minutos la primera vez)

```bash
docker compose ps
```

`airflow-init` debe aparecer como `exited (0)` y el resto como `running` / `healthy`. Si algo falla: `docker compose logs airflow-init`.

## 5. Entrar a Airflow

- URL: http://localhost:8080
- Usuario: `admin`
- Contraseña: `admin_demo_pwd` (la de `AIRFLOW_ADMIN_PASSWORD` en `.env`)

## 6. Verificar la Connection y las Variables

**Desde la UI:** *Admin → Connections* (debe existir `warehouse_db`) y *Admin → Variables* (deben existir `RAW_CSV_PATH`, `MAX_REJECT_PCT` y `SOURCE_TIMEZONE`).

**Desde la terminal:**

```bash
docker compose exec airflow-scheduler airflow connections get warehouse_db
docker compose exec airflow-scheduler airflow variables list
```

| Variable | Valor | Uso |
|---|---|---|
| `RAW_CSV_PATH` | `/opt/airflow/data` | Carpeta de los CSV de entrada |
| `SOURCE_TIMEZONE` | `Europe/London` | Zona horaria de las fechas de origen (se convierten a UTC) |
| `MAX_REJECT_PCT` | `5` | % máximo de filas rechazadas antes de detener la carga |

## 7. Ejecutar el pipeline

1. En la lista de DAGs, buscar **`etl_datamart_daily`**.
2. **Activarlo** con el interruptor (viene pausado por defecto).
3. Pulsar **Trigger** (▶) para ejecutarlo ahora. Además queda programado `@daily`.
4. En la vista *Graph* se ven las tareas; toda la corrida tarda unos 2 minutos.

```text
extract_sales_csv   ─┐
                     ├─> transform_transactions -> check_data_quality -> load_warehouse -> refresh_daily_revenue
extract_history_csv ─┘
```

## 8. Verificar que los datos llegaron al Data Warehouse

```bash
docker compose exec postgres-warehouse psql -U warehouse -d datamart -c "SELECT * FROM etl_source_summary ORDER BY priority;"
```

Resultado esperado:

| source | rows_read | rows_loaded | rows_rejected | rows_duplicated |
|---|---|---|---|---|
| sales | 541909 | 534127 | 2517 | 5265 |
| history | 541909 | 0 | 2517 | 539392 |

Más comprobaciones:

```bash
docker compose exec postgres-warehouse psql -U warehouse -d datamart -c "SELECT COUNT(*) FROM fact_transactions;"            # 534127
docker compose exec postgres-warehouse psql -U warehouse -d datamart -c "SELECT COUNT(*) FROM dim_product;"                  # 3828
docker compose exec postgres-warehouse psql -U warehouse -d datamart -c "SELECT COUNT(*) FROM fact_daily_product_revenue;"   # 278011
docker compose exec postgres-warehouse psql -U warehouse -d datamart -c "SELECT rejection_reason, COUNT(*) FROM etl_rejections GROUP BY 1;"
```

**Prueba de idempotencia:** vuelve a pulsar *Trigger* y repite las consultas: los conteos deben ser idénticos.

## 9. Consultas de negocio

Ejecutar todas las consultas:

```bash
# Linux / macOS / Git Bash
docker compose exec -T postgres-warehouse psql -U warehouse -d datamart < include/sql/business_questions.sql
```

```powershell
# Windows PowerShell
Get-Content include/sql/business_questions.sql | docker compose exec -T postgres-warehouse psql -U warehouse -d datamart
```

También puedes conectarte con DBeaver o pgAdmin a `localhost:5433` (base `datamart`, usuario `warehouse`, contraseña `warehouse_demo_pwd`) y abrir el archivo.

| # | Pregunta |
|---|---|
| 0 | Validación de la carga por fuente y rechazos por motivo |
| 1 | Evolución mensual de las ventas netas |
| 2 | Revenue bruto y % de devolución por categoría |
| 3 | Top 10 productos por revenue neto y por tasa de devolución |
| 4 | Transacciones y ticket promedio por país |
| 5 | Clientes identificados vs. transacciones sin customer ID |
| 6 | Productos con descripción inconsistente y total de códigos únicos |
| 7 | Soporte de la recomendación al equipo de producto |

Las respuestas y la recomendación están en [docs/decisiones_tecnicas.md](docs/decisiones_tecnicas.md) (secciones 5 y 8).

## 10. Exploración de las fuentes (opcional)

```bash
docker compose exec airflow-scheduler python /opt/airflow/include/scripts/explore_data.py
```

## 11. Detener o reiniciar desde cero

```bash
docker compose down        # detiene y conserva los datos
docker compose down -v     # borra también las bases: la próxima vez se recrean las tablas
```

> Si cambias `.env` o `01_create_tables.sql` después de la primera ejecución, usa `docker compose down -v`. PostgreSQL solo aplica el usuario, la contraseña y el DDL cuando crea el volumen por primera vez.

## 12. Seguridad

- El `.env` real está en `.gitignore`; en el repositorio solo está `.env.example`, con valores de **demo** para correr en local.
- El código no tiene usuarios, contraseñas ni cadenas de conexión: el DAG usa la Connection `warehouse_db`, que se crea a partir del `.env`.
- `.gitattributes` fuerza fin de línea LF en los `.sh`, para que `init_airflow.sh` funcione aunque se clone en Windows.
