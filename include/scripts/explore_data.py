"""
Exploración de las fuentes crudas (NO es parte del DAG).

Uso:
    docker compose exec airflow-scheduler python /opt/airflow/include/scripts/explore_data.py

Los resultados están resumidos en docs/decisiones_tecnicas.md (sección 2).
"""

import csv
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from datamart_etl import config

DATA_DIR = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/airflow/data")
STANDARD_CODE = re.compile(r"^\d{5}[A-Z]{0,2}$")


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def inspect_source(source):
    path = DATA_DIR / source["file"]
    print(f"\n{'=' * 70}\nFUENTE: {source['name']} ({source['file']}, {source['encoding']})\n{'=' * 70}")

    with path.open("r", encoding=source["encoding"], newline="") as file:
        reader = csv.DictReader(file)
        columns = reader.fieldnames or []
        rows = list(reader)

    print("Columnas:", columns)
    print("Filas:", len(rows))

    # Nulos por columna
    nulls = {col: sum(1 for r in rows if not (r[col] or "").strip()) for col in columns}
    print("Vacíos por columna:", {c: n for c, n in nulls.items() if n})

    # Tipos y rangos
    quantity_col = next(c for c in columns if config.COLUMN_ALIASES.get(c) == "quantity")
    price_col = next(c for c in columns if config.COLUMN_ALIASES.get(c) == "unit_price")
    date_col = next(c for c in columns if config.COLUMN_ALIASES.get(c) == "invoice_date")
    code_col = next(c for c in columns if config.COLUMN_ALIASES.get(c) == "stock_code")
    desc_col = next(c for c in columns if config.COLUMN_ALIASES.get(c) == "description")
    invoice_col = next(c for c in columns if config.COLUMN_ALIASES.get(c) == "invoice_no")

    quantities = [to_float(r[quantity_col]) for r in rows]
    prices = [to_float(r[price_col]) for r in rows]
    print(f"Cantidad: min={min(q for q in quantities if q is not None)}, "
          f"max={max(q for q in quantities if q is not None)}, "
          f"<0: {sum(1 for q in quantities if q is not None and q < 0)}, "
          f"=0: {sum(1 for q in quantities if q == 0)}")
    print(f"Precio: min={min(p for p in prices if p is not None)}, "
          f"max={max(p for p in prices if p is not None)}, "
          f"<=0: {sum(1 for p in prices if p is not None and p <= 0)}")

    dates = [datetime.strptime(r[date_col].strip(), config.DATE_FORMATS[0]) for r in rows]
    print(f"Fechas: {min(dates)} -> {max(dates)} (sin zona horaria)")

    print("Facturas de cancelación (empiezan con C):",
          sum(1 for r in rows if r[invoice_col].startswith("C")))

    # Duplicados exactos
    signatures = Counter(tuple(r[c] for c in columns if c != "index") for r in rows)
    print("Filas duplicadas exactas:", sum(n - 1 for n in signatures.values() if n > 1))

    # Códigos fuera del patrón de 5 dígitos
    odd_codes = Counter(
        "".join(r[code_col].upper().split()) for r in rows
        if not STANDARD_CODE.match("".join(r[code_col].upper().split()))
    )
    print("Códigos fuera del patrón (top 10):", odd_codes.most_common(10))

    # Descripciones inconsistentes
    descriptions = defaultdict(set)
    for r in rows:
        if (r[desc_col] or "").strip():
            descriptions[r[code_col].upper().strip()].add(r[desc_col].strip())
    print("Códigos únicos:", len({r[code_col].upper().strip() for r in rows}))
    print("Códigos con más de una descripción:", sum(1 for d in descriptions.values() if len(d) > 1))


def main():
    for source in config.SOURCES:
        inspect_source(source)


if __name__ == "__main__":
    main()
