"""
TRANSFORMACIÓN: aplica las reglas de negocio a las filas extraídas.

Por cada fila:
  1. Se limpia y valida. Si falla, va a rejections.csv con su motivo.
  2. Se calcula su clave de negocio. Si ya se vio, es un duplicado y se descarta.
  3. Si pasa, va a transactions.csv.

Al final se arma el catálogo de productos (products.csv) y un resumen por
fuente (source_summary.csv).
"""

import csv
import hashlib
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from datamart_etl import config
from datamart_etl.extract import get_work_dir, raw_file_path

logger = logging.getLogger(__name__)

TRANSACTION_COLUMNS = [
    "transaction_key", "source", "source_row_number", "invoice_no", "stock_code",
    "customer_id", "country", "invoice_date_utc", "quantity", "unit_price",
    "line_amount", "transaction_type", "description_raw",
]
REJECTION_COLUMNS = [
    "source", "source_row_number", "invoice_no", "stock_code",
    "rejection_reason", "rejected_value",
]
PRODUCT_COLUMNS = ["stock_code", "description", "category", "is_product", "description_variants"]
SUMMARY_COLUMNS = ["source", "priority", "rows_read", "rows_loaded", "rows_rejected", "rows_duplicated"]


class RejectedRow(Exception):
    """Se lanza cuando una fila no cumple una regla. Lleva el motivo y el valor."""

    def __init__(self, reason, value=""):
        super().__init__(reason)
        self.reason = reason
        self.value = value


# ---------------------------------------------------------------------------
# Funciones de limpieza: una por campo
# ---------------------------------------------------------------------------

def clean_text(value):
    """Quita espacios sobrantes. Texto vacío -> None."""
    value = " ".join((value or "").split())
    return value or None


def clean_stock_code(value):
    """Regla de negocio: mayúsculas y sin espacios ('bank charges' -> 'BANKCHARGES')."""
    return "".join((value or "").upper().split()) or None


def clean_customer_id(value):
    """'17850.0' y '17850' son el mismo cliente -> '17850'. Vacío -> None."""
    value = clean_text(value)
    if value and value.endswith(".0"):
        value = value[:-2]
    return value


def parse_quantity(value):
    try:
        number = Decimal(value.strip())
    except (InvalidOperation, AttributeError):
        raise RejectedRow(config.REJECT_INVALID_QUANTITY, value)
    if number != number.to_integral_value():
        raise RejectedRow(config.REJECT_INVALID_QUANTITY, value)
    return int(number)


def parse_price(value):
    try:
        price = Decimal(value.strip())
    except (InvalidOperation, AttributeError):
        raise RejectedRow(config.REJECT_INVALID_PRICE, value)
    # Regla de negocio: el precio de una transacción válida debe ser > 0.
    if price <= 0:
        raise RejectedRow(config.REJECT_PRICE_NOT_POSITIVE, value)
    return price


def parse_date_to_utc(value, source_tz):
    """Las fechas vienen sin zona: se interpretan en la zona de la fuente y se pasan a UTC."""
    for date_format in config.DATE_FORMATS:
        try:
            local_date = datetime.strptime(value.strip(), date_format)
        except ValueError:
            continue
        return local_date.replace(tzinfo=source_tz).astimezone(timezone.utc)
    raise RejectedRow(config.REJECT_INVALID_DATE, value)


def transaction_type_for(quantity):
    """Regla de negocio: cantidad <= 0 no es venta."""
    if quantity > 0:
        return "SALE"
    if quantity < 0:
        return "RETURN"
    return "ADJUSTMENT"


def business_key(record):
    """
    Identifica una línea de factura sin importar de qué fuente venga:
    factura + producto + fecha + cantidad + precio.
    Se calcula con los valores YA limpios, así '18' y '18.0' dan la misma clave.
    """
    parts = [
        record["invoice_no"],
        record["stock_code"],
        record["invoice_date_utc"],
        str(record["quantity"]),
        format(record["unit_price"].normalize(), "f"),  # 18.0 -> "18"
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def clean_row(row, source_name, source_tz):
    """Convierte una fila cruda en una transacción limpia o lanza RejectedRow."""
    invoice_no = clean_text(row["invoice_no"])
    if not invoice_no:
        raise RejectedRow(config.REJECT_EMPTY_INVOICE)

    stock_code = clean_stock_code(row["stock_code"])
    if not stock_code:
        raise RejectedRow(config.REJECT_EMPTY_STOCK_CODE)

    quantity = parse_quantity(row["quantity"])
    unit_price = parse_price(row["unit_price"])
    invoice_date_utc = parse_date_to_utc(row["invoice_date"], source_tz).isoformat()

    # Revenue de la línea = cantidad x precio. Es negativo en las devoluciones.
    line_amount = (Decimal(quantity) * unit_price).quantize(Decimal("0.01"), ROUND_HALF_UP)

    return {
        "source": source_name,
        "source_row_number": row["row_number"],
        "invoice_no": invoice_no,
        "stock_code": stock_code,
        "customer_id": clean_customer_id(row["customer_id"]),
        "country": clean_text(row["country"]),
        "invoice_date_utc": invoice_date_utc,
        "quantity": quantity,
        "unit_price": unit_price,
        "line_amount": line_amount,
        "transaction_type": transaction_type_for(quantity),
        "description_raw": clean_text(row["description"]),
    }


# ---------------------------------------------------------------------------
# Catálogo de productos
# ---------------------------------------------------------------------------

def is_product(stock_code):
    if stock_code in config.NON_PRODUCT_CODES:
        return False
    return not stock_code.startswith(config.NON_PRODUCT_PREFIXES)


def category_for(stock_code, description):
    """Primera categoría cuyas palabras clave aparezcan en la descripción."""
    if not is_product(stock_code):
        return config.NON_PRODUCT_CATEGORY
    words = set(re.findall(r"[A-Z0-9-]+", description or ""))
    for category, keywords in config.CATEGORY_KEYWORDS:
        if words & keywords:
            return category
    return config.DEFAULT_CATEGORY


def canonical_description(description_counts):
    """
    Nombre canónico = la descripción (en mayúsculas) que más se repite.
    Si hay empate, gana la primera en orden alfabético, para que el
    resultado sea siempre el mismo.
    """
    if not description_counts:
        return None
    return sorted(description_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def build_products(descriptions_by_code):
    products = []
    for stock_code in sorted(descriptions_by_code):
        counts = descriptions_by_code[stock_code]
        description = canonical_description(counts)
        products.append({
            "stock_code": stock_code,
            "description": description,
            "category": category_for(stock_code, description),
            "is_product": is_product(stock_code),
            "description_variants": len(counts),
        })
    return products


# ---------------------------------------------------------------------------
# Proceso completo
# ---------------------------------------------------------------------------

def write_csv(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def transform_all(data_dir, source_timezone):
    """Transforma todas las fuentes en orden de prioridad. Devuelve el resumen por fuente."""
    work_dir = get_work_dir(data_dir)
    source_tz = ZoneInfo(source_timezone)

    seen_keys = set()                             # claves ya cargadas (para detectar duplicados)
    descriptions_by_code = defaultdict(Counter)   # stock_code -> {descripción: veces}
    summary = []

    with (work_dir / "transactions.csv").open("w", encoding="utf-8", newline="") as tx_file, \
         (work_dir / "rejections.csv").open("w", encoding="utf-8", newline="") as rej_file:

        tx_writer = csv.DictWriter(tx_file, fieldnames=TRANSACTION_COLUMNS)
        rej_writer = csv.DictWriter(rej_file, fieldnames=REJECTION_COLUMNS)
        tx_writer.writeheader()
        rej_writer.writeheader()

        for priority, source in enumerate(config.SOURCES, start=1):
            stats = {"source": source["name"], "priority": priority, "rows_read": 0,
                     "rows_loaded": 0, "rows_rejected": 0, "rows_duplicated": 0}

            with raw_file_path(data_dir, source["name"]).open("r", encoding="utf-8", newline="") as raw:
                for row in csv.DictReader(raw):
                    stats["rows_read"] += 1

                    # 1. Limpiar y validar
                    try:
                        record = clean_row(row, source["name"], source_tz)
                    except RejectedRow as rejection:
                        stats["rows_rejected"] += 1
                        rej_writer.writerow({
                            "source": source["name"],
                            "source_row_number": row["row_number"],
                            "invoice_no": clean_text(row["invoice_no"]),
                            "stock_code": clean_stock_code(row["stock_code"]),
                            "rejection_reason": rejection.reason,
                            "rejected_value": rejection.value,
                        })
                        continue

                    # 2. Duplicados (dentro de la fuente o con una fuente de mayor prioridad)
                    key = business_key(record)
                    if key in seen_keys:
                        stats["rows_duplicated"] += 1
                        continue
                    seen_keys.add(key)

                    # 3. Transacción válida
                    record["transaction_key"] = key
                    tx_writer.writerow(record)
                    stats["rows_loaded"] += 1

                    counts = descriptions_by_code[record["stock_code"]]
                    if record["description_raw"]:
                        counts[record["description_raw"].upper()] += 1

            logger.info("Fuente %s transformada: %s", source["name"], stats)
            summary.append(stats)

    write_csv(work_dir / "products.csv", PRODUCT_COLUMNS, build_products(descriptions_by_code))
    write_csv(work_dir / "source_summary.csv", SUMMARY_COLUMNS, summary)
    return summary
