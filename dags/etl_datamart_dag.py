"""
DAG diario del pipeline de DataMart S.A.S.

    extract_sales_csv   ─┐
                         ├─> transform_transactions -> check_data_quality
    extract_history_csv ─┘        -> load_warehouse -> refresh_daily_revenue

- Las tareas se pasan los datos por archivos en <RAW_CSV_PATH>/work/
  (no por XCom, porque son ~1 millón de filas).
- Las Variables se leen con plantillas {{ var.value.X }}: se resuelven cuando
  la tarea corre, no cada vez que Airflow lee este archivo.
- La lógica está en include/datamart_etl/; este archivo solo orquesta.
"""

from datetime import datetime, timedelta

from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG

from datamart_etl import config, extract, load, quality, transform

WAREHOUSE_CONN_ID = "warehouse_db"   # Airflow Connection creada por init_airflow.sh
DATA_DIR = "{{ var.value.RAW_CSV_PATH }}"


def load_to_warehouse(data_dir):
    """Abre la conexión con la Airflow Connection y carga los archivos."""
    connection = PostgresHook(postgres_conn_id=WAREHOUSE_CONN_ID).get_conn()
    try:
        load.load_warehouse(connection, data_dir)
    finally:
        connection.close()


default_args = {
    "owner": "datamart",
    "retries": 2,                         # reintentos automáticos ante fallos
    "retry_delay": timedelta(minutes=2),
    "execution_timeout": timedelta(minutes=20),
}

with DAG(
    dag_id="etl_datamart_daily",
    description="ETL diario: CSV de ventas -> Data Warehouse PostgreSQL",
    default_args=default_args,
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    max_active_runs=1,                    # nunca dos corridas a la vez sobre las mismas tablas
    template_searchpath=["/opt/airflow/include/sql"],
    tags=["etl", "datamart", "postgres"],
) as dag:

    # 1. Extracción: una tarea por fuente (se generan desde config.SOURCES).
    extract_tasks = [
        PythonOperator(
            task_id=f"extract_{source['name']}_csv",
            python_callable=extract.extract_source,
            op_kwargs={"source_name": source["name"], "data_dir": DATA_DIR},
        )
        for source in config.SOURCES
    ]

    # 2. Transformación: reglas de negocio, rechazos y duplicados entre fuentes.
    transform_transactions = PythonOperator(
        task_id="transform_transactions",
        python_callable=transform.transform_all,
        op_kwargs={
            "data_dir": DATA_DIR,
            "source_timezone": "{{ var.value.SOURCE_TIMEZONE }}",
        },
    )

    # 3. Calidad: si hay demasiados rechazos, se detiene antes de cargar.
    check_data_quality = PythonOperator(
        task_id="check_data_quality",
        python_callable=quality.check_quality,
        op_kwargs={
            "data_dir": DATA_DIR,
            "max_reject_pct": "{{ var.value.MAX_REJECT_PCT }}",
        },
        retries=0,  # si los datos están mal, reintentar no lo arregla
    )

    # 4. Carga: reemplaza las tablas en una sola transacción (idempotente).
    load_warehouse = PythonOperator(
        task_id="load_warehouse",
        python_callable=load_to_warehouse,
        op_kwargs={"data_dir": DATA_DIR},
    )

    # 5. Revenue bruto / devoluciones / neto por producto y día.
    refresh_daily_revenue = SQLExecuteQueryOperator(
        task_id="refresh_daily_revenue",
        conn_id=WAREHOUSE_CONN_ID,
        sql="refresh_daily_revenue.sql",
    )

    extract_tasks >> transform_transactions >> check_data_quality >> load_warehouse >> refresh_daily_revenue
