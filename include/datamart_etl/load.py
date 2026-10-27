"""
CARGA: reemplaza el contenido del Data Warehouse con los archivos de work/.

Idempotencia: todo ocurre en UNA transacción
  1. TRUNCATE de las tablas
  2. COPY de cada archivo
  3. Verificación de conteos
Si algo falla, PostgreSQL hace rollback y las tablas quedan como estaban.
Si se corre dos veces con los mismos archivos, el resultado es idéntico.
"""

import csv
import logging

from datamart_etl.extract import get_work_dir
from datamart_etl.transform import (
    PRODUCT_COLUMNS,
    REJECTION_COLUMNS,
    SUMMARY_COLUMNS,
    TRANSACTION_COLUMNS,
)

logger = logging.getLogger(__name__)

# Orden importante: dim_product va antes que fact_transactions (llave foránea).
FILES_TO_LOAD = [
    ("dim_product", "products.csv", PRODUCT_COLUMNS),
    ("fact_transactions", "transactions.csv", TRANSACTION_COLUMNS),
    ("etl_rejections", "rejections.csv", REJECTION_COLUMNS),
    ("etl_source_summary", "source_summary.csv", SUMMARY_COLUMNS),
]

TRUNCATE_SQL = """
    TRUNCATE fact_daily_product_revenue, fact_transactions, dim_product,
             etl_rejections, etl_source_summary;
"""


def count_rows(path):
    with path.open(encoding="utf-8", newline="") as file:
        return sum(1 for _ in csv.DictReader(file))


def load_warehouse(connection, data_dir):
    """Recibe una conexión psycopg2 abierta (la crea el DAG con la Connection de Airflow)."""
    work_dir = get_work_dir(data_dir)

    with connection:  # commit al final, o rollback si hay error
        with connection.cursor() as cursor:
            cursor.execute(TRUNCATE_SQL)

            for table, filename, columns in FILES_TO_LOAD:
                path = work_dir / filename
                with path.open(encoding="utf-8") as file:
                    cursor.copy_expert(
                        f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH (FORMAT csv, HEADER true)",
                        file,
                    )

                # Verificación: lo que hay en la tabla == lo que había en el archivo.
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                in_table = cursor.fetchone()[0]
                in_file = count_rows(path)
                if in_table != in_file:
                    raise ValueError(f"{table}: el archivo tiene {in_file} filas y la tabla {in_table}")

                logger.info("%s cargada: %s filas", table, in_table)
