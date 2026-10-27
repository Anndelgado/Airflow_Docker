"""
Configuración y decisiones de negocio del pipeline.

Todo lo que es una DECISIÓN (y no lógica) vive en este archivo, para que
se pueda cambiar sin tocar el resto del código.
"""

# ---------------------------------------------------------------------------
# 1. Fuentes de datos, en ORDEN DE PRIORIDAD.
#    Si la misma línea de factura aparece en las dos fuentes, se conserva
#    la de la fuente que está primero en esta lista.
# ---------------------------------------------------------------------------
SOURCES = [
    {"name": "sales", "file": "data.csv", "encoding": "cp1252"},
    {"name": "history", "file": "online_retail.csv", "encoding": "utf-8-sig"},
]

# Carpeta (dentro de RAW_CSV_PATH) donde las tareas dejan sus archivos
# intermedios para la siguiente tarea.
WORK_FOLDER = "work"

# ---------------------------------------------------------------------------
# 2. Nombres de columna que puede traer cada fuente -> nombre estándar.
#    Incluye los nombres del dataset online_retail_II (Invoice, Price,
#    Customer ID) por si se vuelve a usar esa fuente.
# ---------------------------------------------------------------------------
COLUMN_ALIASES = {
    "InvoiceNo": "invoice_no",
    "Invoice": "invoice_no",
    "StockCode": "stock_code",
    "Description": "description",
    "Quantity": "quantity",
    "InvoiceDate": "invoice_date",
    "UnitPrice": "unit_price",
    "Price": "unit_price",
    "CustomerID": "customer_id",
    "Customer ID": "customer_id",
    "Country": "country",
}

STANDARD_COLUMNS = [
    "invoice_no",
    "stock_code",
    "description",
    "quantity",
    "invoice_date",
    "unit_price",
    "customer_id",
    "country",
]

# Sin estas columnas la fuente no se puede procesar.
REQUIRED_COLUMNS = {"invoice_no", "stock_code", "quantity", "invoice_date", "unit_price"}

# Formatos de fecha aceptados (las fechas vienen sin zona horaria).
DATE_FORMATS = ("%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M:%S")

# ---------------------------------------------------------------------------
# 3. Códigos que NO son productos (envíos, comisiones, descuentos, ajustes,
#    bonos de regalo). Se cargan, pero marcados con is_product = FALSE para
#    excluirlos de los análisis de producto.
# ---------------------------------------------------------------------------
NON_PRODUCT_CODES = {
    "POST",         # Envío (POSTAGE)
    "DOT",          # Envío tienda online (DOTCOM POSTAGE)
    "C2",           # Transporte (CARRIAGE)
    "M",            # Ajuste manual
    "D",            # Descuento
    "S",            # Muestras (SAMPLES)
    "B",            # Ajuste de deuda incobrable
    "BANKCHARGES",  # Comisiones bancarias
    "AMAZONFEE",    # Comisión de Amazon
    "CRUK",         # Comisión CRUK
}
NON_PRODUCT_PREFIXES = ("GIFT_",)  # Bonos de regalo (GIFT_0001_20, ...)
NON_PRODUCT_CATEGORY = "Cargos y ajustes"

# ---------------------------------------------------------------------------
# 4. Categoría de producto. No hay API de catálogo, así que se asigna por
#    palabras clave en la descripción canónica. Se revisan en este orden y
#    gana la PRIMERA categoría que tenga una palabra en común.
# ---------------------------------------------------------------------------
CATEGORY_KEYWORDS = [
    ("Electrónica", {
        "LED", "LIGHTS", "LAMP", "TORCH", "RADIO", "CLOCK", "BATTERY",
        "CALCULATOR", "ALARM", "ELECTRIC", "USB", "NIGHTLIGHT", "LIGHT",
    }),
    ("Papelería", {
        "CARD", "CARDS", "PAPER", "NOTEBOOK", "NOTEBOOKS", "PEN", "PENS",
        "PENCIL", "PENCILS", "STICKER", "STICKERS", "ENVELOPE", "ENVELOPES",
        "WRAP", "TAPE", "CALENDAR", "DIARY", "JOURNAL", "BOOK", "NOTEPAD",
        "TAG", "TAGS", "ERASER", "RULER", "CRAYONS", "CHALK", "STATIONERY",
        "ALBUM", "BOOKMARK", "CRAFT", "FELTCRAFT", "MEMO", "MEMOBOARD",
        "BOARD", "PAINT", "RIBBON", "RIBBONS", "STAMP", "STAMPS",
    }),
    ("Ropa", {
        "BAG", "BAGS", "HANDBAG", "PURSE", "APRON", "SCARF", "HAT", "GLOVES",
        "SLIPPERS", "SOCKS", "UMBRELLA", "NECKLACE", "BRACELET", "EARRINGS",
        "JEWELLERY", "BROOCH", "HAIR", "WALLET", "SHIRT", "BACKPACK",
        "SHOPPER", "PARASOL", "FAN", "WARMER", "GLOSS",
    }),
    ("Deportes", {
        "BALL", "BALLS", "GAME", "GAMES", "SKIPPING", "KITE", "BICYCLE",
        "FOOTBALL", "CRICKET", "TENNIS", "GOLF", "SPORT", "SPORTS", "PICNIC",
        "CAMPING", "BADMINTON", "SKITTLES", "DOMINOES", "JIGSAW", "ROUNDERS",
        "BLOCK", "BLOCKS", "GLIDERS", "TOY", "TOYS", "PUZZLE",
    }),
    ("Hogar", {
        "CANDLE", "CANDLES", "HOLDER", "T-LIGHT", "T-LIGHTS", "MUG", "MUGS",
        "CUP", "CUPS", "PLATE", "PLATES", "BOWL", "BOWLS", "CUSHION", "FRAME",
        "JAR", "JARS", "TIN", "TINS", "LANTERN", "BOTTLE", "VASE", "DOORMAT",
        "BASKET", "TRAY", "TEA", "CAKE", "KITCHEN", "SPOON", "GLASS", "HOOK",
        "HANGER", "BOX", "BOXES", "STORAGE", "COASTER", "COASTERS", "TOWEL",
        "NAPKINS", "DOORSTOP", "MIRROR", "SIGN", "DECORATION", "ORNAMENT",
        "WREATH", "BUNTING", "CHRISTMAS", "HEART", "CASES", "LUNCH", "PANTRY",
        "CAKESTAND", "TEACUP", "SAUCER", "TEAPOT", "BAKING", "CUTLERY", "CHEST",
        "CABINET", "DRAWER", "RACK", "BIN", "JUG", "PEGS", "JAM", "GARDEN",
        "GARDENERS", "DISH", "TRAYS", "CLOTHES", "CERAMIC", "WOODEN",
    }),
]
# Es una heurística: cubre ~91% del revenue; el resto queda en "Otros".
# Cuando exista la API de catálogo, esta lista se reemplaza por su categoría.
DEFAULT_CATEGORY = "Otros"

# ---------------------------------------------------------------------------
# 5. Clientes sin ID: se CONSERVAN con customer_id = NULL (no se descartan
#    ventas reales). En las consultas se muestran como "Sin cliente".
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 6. Motivos de rechazo (quedan en la tabla etl_rejections).
# ---------------------------------------------------------------------------
REJECT_EMPTY_INVOICE = "Número de factura vacío"
REJECT_EMPTY_STOCK_CODE = "Código de producto vacío"
REJECT_INVALID_QUANTITY = "Cantidad no numérica o no entera"
REJECT_INVALID_PRICE = "Precio unitario no numérico"
REJECT_PRICE_NOT_POSITIVE = "Precio unitario menor o igual a cero"
REJECT_INVALID_DATE = "Fecha inválida"
