#!/bin/bash
# Testea la imagen de Cloud Run localmente antes de deployar a GCP.
# Útil para detectar problemas de build o ejecución sin costo.
#
# Uso:
#   ./test_cloud_run_local.sh              # testea reddit (default)
#   ./test_cloud_run_local.sh hotmart      # testea hotmart
#   ./test_cloud_run_local.sh --run        # ejecuta de verdad (no dry-run)
#
# Lee variables de entorno del archivo .env automáticamente.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="scrapper-cloudrun-test"
SPIDER="reddit"
RUN_MODE=false

# Detectar spider y flag --run en cualquier posición
for arg in "$@"; do
    case "$arg" in
        --run) RUN_MODE=true ;;
        --dry-run) RUN_MODE=false ;;
        *) SPIDER="$arg" ;;
    esac
done

# ── Cargar variables del .env ──
ENV_FILE="${SCRIPT_DIR}/.env"
if [ -f "$ENV_FILE" ]; then
    echo "✅ Cargando variables desde ${ENV_FILE}"
    set -a
    source "$ENV_FILE"
    set +a
else
    echo "⚠️  No se encontró ${ENV_FILE}"
fi

# ── Validar variables críticas ──
if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_KEY" ] || [ -z "$OPENAI_API_KEY" ]; then
    echo "❌ ERROR: Faltan variables de entorno requeridas."
    echo ""
    echo "Asegúrate de que el archivo .env contenga:"
    echo "  SUPABASE_URL=https://tu-proyecto.supabase.co"
    echo "  SUPABASE_KEY=tu-service-role-key"
    echo "  OPENAI_API_KEY=sk-..."
    echo ""
    echo "O expórtalas manualmente antes de correr el script:"
    echo "  export SUPABASE_URL=..."
    exit 1
fi

echo "═══════════════════════════════════════════"
echo "  Cloud Run Local Test"
echo "  Spider: ${SPIDER}"
echo "═══════════════════════════════════════════"

# 1. Build
echo ""
echo "[1/3] Building Docker image..."
docker build -f "${SCRIPT_DIR}/Dockerfile.cloudrun" -t "$IMAGE_NAME" "${SCRIPT_DIR}"

# 2. Run with env vars
echo ""
if [ "$RUN_MODE" == "true" ]; then
    echo "[2/3] Running container (MODO REAL — enviará datos a Supabase)..."
    DOCKER_ARGS="$SPIDER"
else
    echo "[2/3] Running container (dry-run — solo muestra, no ejecuta)..."
    DOCKER_ARGS="$SPIDER --dry-run"
fi

# shellcheck disable=SC2086
docker run --rm \
    --env-file "$ENV_FILE" \
    "$IMAGE_NAME" \
    $DOCKER_ARGS

echo ""
echo "[3/3] Ejecución completada exitosamente."
echo ""
if [ "$RUN_MODE" == "false" ]; then
    echo "Para ejecutar en serio (enviará datos a Supabase):"
    echo "  ./test_cloud_run_local.sh --run"
    echo "  # o"
    echo "  ./test_cloud_run_local.sh ${SPIDER} --run"
    echo ""
fi
echo "Para deployar a Cloud Run:"
echo "  ./deploy_cloud_run.sh"
