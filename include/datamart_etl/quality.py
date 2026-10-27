"""
CALIDAD: compuerta antes de cargar. Si los datos no pasan, el DAG se detiene y no se carga nada al Data Warehouse.
"""

import csv
import logging

from datamart_etl.extract import get_work_dir

logger = logging.getLogger(__name__)


def check_quality(data_dir, max_reject_pct):
    """
    Reglas:
      - Debe haber al menos una transacción válida.
      - El % de filas rechazadas no puede superar MAX_REJECT_PCT.
    (Los duplicados no cuentan como rechazo: no son datos malos, son repetidos.)
    """
    with (get_work_dir(data_dir) / "source_summary.csv").open(encoding="utf-8") as file:
        summary = list(csv.DictReader(file))

    rows_read = sum(int(row["rows_read"]) for row in summary)
    rows_loaded = sum(int(row["rows_loaded"]) for row in summary)
    rows_rejected = sum(int(row["rows_rejected"]) for row in summary)
    reject_pct = 100 * rows_rejected / rows_read if rows_read else 100

    logger.info(
        "Leídas: %s | válidas: %s | rechazadas: %s (%.2f%%) | límite: %s%%",
        rows_read, rows_loaded, rows_rejected, reject_pct, max_reject_pct,
    )

    if rows_loaded == 0:
        raise ValueError("No hay transacciones válidas para cargar.")

    if reject_pct > float(max_reject_pct):
        raise ValueError(
            f"Rechazos {reject_pct:.2f}% superan el límite de {max_reject_pct}%. "
            "Revisar la tabla etl_rejections antes de cargar."
        )

    return {"rows_loaded": rows_loaded, "reject_pct": round(reject_pct, 2)}
