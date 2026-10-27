#!/usr/bin/env bash
# Inicialización automática de Airflow (servicio airflow-init del compose).
# Se puede correr muchas veces: cada paso revisa o reemplaza lo que ya existe.
set -euo pipefail

echo "1/4 Migrando la base de metadatos de Airflow..."
airflow db migrate

echo "2/4 Creando el usuario administrador (si no existe)..."
if ! airflow users list --output json | grep -q "\"username\": \"${AIRFLOW_ADMIN_USER}\""; then
    airflow users create \
        --username "${AIRFLOW_ADMIN_USER}" \
        --password "${AIRFLOW_ADMIN_PASSWORD}" \
        --firstname Admin \
        --lastname DataMart \
        --role Admin \
        --email admin@datamart.local
fi

echo "3/4 Creando la Connection warehouse_db (se recrea para tomar los valores del .env)..."
airflow connections delete warehouse_db >/dev/null 2>&1 || true
airflow connections add warehouse_db \
    --conn-type postgres \
    --conn-host postgres-warehouse \
    --conn-port 5432 \
    --conn-login "${POSTGRES_WAREHOUSE_USER}" \
    --conn-password "${POSTGRES_WAREHOUSE_PASSWORD}" \
    --conn-schema "${POSTGRES_WAREHOUSE_DB}"

echo "4/4 Creando las Variables del pipeline..."
airflow variables set RAW_CSV_PATH "${PIPELINE_RAW_CSV_PATH}"
airflow variables set MAX_REJECT_PCT "${PIPELINE_MAX_REJECT_PCT}"
airflow variables set SOURCE_TIMEZONE "${PIPELINE_SOURCE_TIMEZONE}"

echo "Inicialización completada."
