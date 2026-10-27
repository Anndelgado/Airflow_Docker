"""
EXTRACCIÓN: lee el CSV crudo de una fuente y lo deja en la carpeta work/
con nombres de columna estándar y codificación UTF-8.
"""

import csv
import logging
from pathlib import Path

from datamart_etl import config

logger = logging.getLogger(__name__)


def get_source(source_name):
    """Busca la configuración de una fuente por su nombre."""
    for source in config.SOURCES:
        if source["name"] == source_name:
            return source
    raise ValueError(f"Fuente desconocida: {source_name}")


def get_work_dir(data_dir):
    """Carpeta donde las tareas dejan sus archivos intermedios."""
    work_dir = Path(data_dir) / config.WORK_FOLDER
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def raw_file_path(data_dir, source_name):
    return get_work_dir(data_dir) / f"raw_{source_name}.csv"


def extract_source(source_name, data_dir):
    """
    1. Verifica que el archivo exista.
    2. Verifica que tenga las columnas obligatorias.
    3. Lo copia a work/raw_<fuente>.csv con columnas estándar.
    Devuelve el número de filas extraídas.
    """
    source = get_source(source_name)
    input_path = Path(data_dir) / source["file"]

    if not input_path.exists():
        raise FileNotFoundError(f"No existe el archivo de la fuente {source_name}: {input_path}")

    output_path = raw_file_path(data_dir, source_name)
    rows = 0

    with input_path.open("r", encoding=source["encoding"], newline="") as input_file, \
         output_path.open("w", encoding="utf-8", newline="") as output_file:

        reader = csv.DictReader(input_file)

        # Traducir los nombres de columna de esta fuente a los estándar.
        column_map = {
            original: config.COLUMN_ALIASES[original]
            for original in (reader.fieldnames or [])
            if original in config.COLUMN_ALIASES
        }

        missing = config.REQUIRED_COLUMNS - set(column_map.values())
        if missing:
            raise ValueError(f"A la fuente {source_name} le faltan columnas: {sorted(missing)}")

        writer = csv.DictWriter(output_file, fieldnames=["row_number"] + config.STANDARD_COLUMNS)
        writer.writeheader()

        # row_number = número de fila en el archivo original (para auditoría).
        for row_number, row in enumerate(reader, start=1):
            standard_row = {column: "" for column in config.STANDARD_COLUMNS}
            for original, standard in column_map.items():
                standard_row[standard] = row[original]
            standard_row["row_number"] = row_number
            writer.writerow(standard_row)
            rows += 1

    logger.info("Fuente %s extraída: %s filas -> %s", source_name, rows, output_path)
    return rows
