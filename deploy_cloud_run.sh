#!/bin/bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════
#  deploy_cloud_run.sh
#  Build + deploy de Cloud Run Jobs + Cloud Scheduler
#  Usa Secret Manager para API keys (SUPABASE_KEY, OPENAI_API_KEY)
# ═══════════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUERIES_FILE="${SCRIPT_DIR}/queries.json"

# ── Configuración (ajusta antes de correr) ──
PROJECT_ID="${PROJECT_ID:-}"
REGION="${REGION:-us-central1}"
REPO_NAME="${REPO_NAME:-scrapper}"
IMAGE_NAME="${IMAGE_NAME:-scraper}"
VERSION_TAG="$(date +%Y%m%d-%H%M%S)"
IMAGE_TAG="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:latest"
IMAGE_TAG_VERSIONED="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:${VERSION_TAG}"

# ── Colores ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ── Validaciones ──
if ! command -v gcloud &>/dev/null; then
    log_error "gcloud CLI no está instalado. Instálalo desde: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

if ! command -v jq &>/dev/null; then
    log_error "jq no está instalado. Instálalo: brew install jq (macOS) o apt-get install jq (Linux)"
    exit 1
fi

GCLOUD_VER=$(gcloud version 2>/dev/null | head -1 | grep -oE '^[^0-9]*([0-9]+)' | grep -oE '[0-9]+' || echo "0")
if [ "$GCLOUD_VER" -lt 418 ]; then
    log_error "gcloud >= 418.0.0 requerido (soporte para gcloud run jobs). Actual: ${GCLOUD_VER}"
    exit 1
fi

if [ -z "$PROJECT_ID" ]; then
    PROJECT_ID=$(gcloud config get-value project 2>/dev/null || true)
    if [ -z "$PROJECT_ID" ]; then
        log_error "No se detectó PROJECT_ID. Configúralo con: export PROJECT_ID=tu-proyecto"
        exit 1
    fi
    log_warn "PROJECT_ID no definido, usando: ${PROJECT_ID}"
fi

if [ ! -f "$QUERIES_FILE" ]; then
    log_error "No encontré ${QUERIES_FILE}"
    exit 1
fi

# ── Leer variables de entorno requeridas ──
if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_KEY" ] || [ -z "$OPENAI_API_KEY" ]; then
    log_warn "Variables de entorno faltantes. Intentando leer desde .env..."
    if [ -f "${SCRIPT_DIR}/.env" ]; then
        set -a
        source "${SCRIPT_DIR}/.env"
        set +a
    fi
fi

if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_KEY" ] || [ -z "$OPENAI_API_KEY" ]; then
    log_error "Faltan variables requeridas: SUPABASE_URL, SUPABASE_KEY, OPENAI_API_KEY"
    echo "Configúralas con:"
    echo "  export SUPABASE_URL=https://tu-proyecto.supabase.co"
    echo "  export SUPABASE_KEY=tu-service-role-key"
    echo "  export OPENAI_API_KEY=sk-..."
    exit 1
fi

# ── Service account dedicada (mejor seguridad que la default) ──
SA_NAME="scrapper-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

if ! gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID" &>/dev/null; then
    log_info "Creando service account dedicada ${SA_EMAIL}..."
    gcloud iam service-accounts create "$SA_NAME" \
        --display-name="Scrapper Cloud Run Jobs" \
        --project="$PROJECT_ID"
fi

# ── Otorgar roles necesarios a la service account ──
log_info "Configurando roles para la service account..."
for ROLE in roles/run.invoker roles/logging.logWriter; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="$ROLE" \
        --condition=None \
        &>/dev/null || true
done

# ── Habilitar APIs si es necesario ──
log_info "Verificando APIs necesarias..."
gcloud services enable run.googleapis.com \
    cloudbuild.googleapis.com \
    cloudscheduler.googleapis.com \
    secretmanager.googleapis.com \
    --project="$PROJECT_ID" || true

# ── Crear repositorio Artifact Registry si no existe ──
log_info "Configurando Artifact Registry..."
gcloud artifacts repositories describe "$REPO_NAME" --location="$REGION" --project="$PROJECT_ID" &>/dev/null || {
    log_info "Creando repositorio ${REPO_NAME} en ${REGION}..."
    gcloud artifacts repositories create "$REPO_NAME" \
        --repository-format=docker \
        --location="$REGION" \
        --description="Scrapper images" \
        --project="$PROJECT_ID"
}

# ── Configurar Docker auth para Artifact Registry ──
log_info "Autenticando Docker con Artifact Registry..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# ── Secret Manager: crear/actualizar secrets para API keys ──
log_info "Configurando secrets en Secret Manager..."
ensure_secret() {
    local name="$1" value="$2"
    if gcloud secrets describe "$name" --project="$PROJECT_ID" &>/dev/null; then
        echo -n "$value" | gcloud secrets versions add "$name" --data-file=- --project="$PROJECT_ID"
        log_info "  Secret '${name}' actualizado."
    else
        echo -n "$value" | gcloud secrets create "$name" \
            --replication-policy=automatic \
            --data-file=- \
            --project="$PROJECT_ID"
        log_info "  Secret '${name}' creado."
    fi
}

ensure_secret "supabase-key" "$SUPABASE_KEY"
ensure_secret "openai-api-key" "$OPENAI_API_KEY"

log_info "Otorgando acceso a Secret Manager para la service account..."
for SECRET_NAME in supabase-key openai-api-key; do
    gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="roles/secretmanager.secretAccessor" \
        --project="$PROJECT_ID" \
        &>/dev/null || true
done

# ── Build + push imagen ──
log_info "Build de imagen Docker (puede tomar varios minutos)..."
gcloud builds submit "${SCRIPT_DIR}" \
    --config="${SCRIPT_DIR}/cloudbuild.yaml" \
    --project="$PROJECT_ID" \
    --substitutions="_REGION=${REGION},_REPO=${REPO_NAME},_IMAGE=${IMAGE_NAME},_TAG=${VERSION_TAG}" \
    || {
        log_warn "cloudbuild.yaml no encontrado o falló, usando build directo..."
        gcloud builds submit "${SCRIPT_DIR}" \
            --tag "$IMAGE_TAG" \
            --tag "$IMAGE_TAG_VERSIONED" \
            --project="$PROJECT_ID"
    }

# ── Leer spiders de queries.json ──
SPIDERS=$(jq -r 'keys[]' "$QUERIES_FILE")

log_info "Spiders detectados: $(echo $SPIDERS | tr '\n' ' ')"

# ── Crear/actualizar jobs + schedulers ──
for SPIDER in $SPIDERS; do
    CONFIG=$(jq -r ".\"${SPIDER}\"" "$QUERIES_FILE")
    SCHEDULE=$(echo "$CONFIG" | jq -r '.schedule')
    CPU=$(echo "$CONFIG" | jq -r '.cloud_run.cpu // 1')
    MEMORY=$(echo "$CONFIG" | jq -r '.cloud_run.memory // "1Gi"')
    TIMEOUT=$(echo "$CONFIG" | jq -r '.cloud_run.timeout // "15m"')

    JOB_NAME="scrapper-${SPIDER}"
    SCHEDULER_NAME="${JOB_NAME}-trigger"

    log_info "────────────────────────────────────────"
    log_info "Configurando ${JOB_NAME}"
    log_info "  Schedule: ${SCHEDULE}"
    log_info "  CPU: ${CPU} | Memory: ${MEMORY} | Timeout: ${TIMEOUT}"

    # Crear o actualizar Cloud Run Job
    if gcloud run jobs describe "$JOB_NAME" --region="$REGION" --project="$PROJECT_ID" &>/dev/null; then
        log_info "Actualizando job existente ${JOB_NAME}..."
        gcloud run jobs update "$JOB_NAME" \
            --image "$IMAGE_TAG" \
            --region "$REGION" \
            --project "$PROJECT_ID" \
            --cpu "${CPU}" \
            --memory "${MEMORY}" \
            --task-timeout "${TIMEOUT}" \
            --args "$SPIDER" \
            --set-env-vars "SUPABASE_URL=${SUPABASE_URL}" \
            --set-secrets "SUPABASE_KEY=supabase-key:latest,OPENAI_API_KEY=openai-api-key:latest" \
            --max-retries 0 \
            --service-account "$SA_EMAIL" \
            --labels "spider=${SPIDER},environment=production,managed-by=deploy-script"
    else
        log_info "Creando job ${JOB_NAME}..."
        gcloud run jobs create "$JOB_NAME" \
            --image "$IMAGE_TAG" \
            --region "$REGION" \
            --project "$PROJECT_ID" \
            --cpu "${CPU}" \
            --memory "${MEMORY}" \
            --task-timeout "${TIMEOUT}" \
            --args "$SPIDER" \
            --set-env-vars "SUPABASE_URL=${SUPABASE_URL}" \
            --set-secrets "SUPABASE_KEY=supabase-key:latest,OPENAI_API_KEY=openai-api-key:latest" \
            --max-retries 0 \
            --service-account "$SA_EMAIL" \
            --labels "spider=${SPIDER},environment=production,managed-by=deploy-script"
    fi

    # Crear o actualizar Cloud Scheduler
    SCHEDULER_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"

    if gcloud scheduler jobs describe "$SCHEDULER_NAME" --location="$REGION" --project="$PROJECT_ID" &>/dev/null; then
        log_info "Actualizando scheduler ${SCHEDULER_NAME}..."
        gcloud scheduler jobs update http "$SCHEDULER_NAME" \
            --schedule="$SCHEDULE" \
            --location="$REGION" \
            --project="$PROJECT_ID" \
            --uri="$SCHEDULER_URI" \
            --http-method POST \
            --oauth-service-account-email "$SA_EMAIL" \
            --max-retry-attempts=3 \
            --min-backoff=5m \
            --max-backoff=1h
    else
        log_info "Creando scheduler ${SCHEDULER_NAME}..."
        gcloud scheduler jobs create http "$SCHEDULER_NAME" \
            --schedule="$SCHEDULE" \
            --location="$REGION" \
            --project="$PROJECT_ID" \
            --uri="$SCHEDULER_URI" \
            --http-method POST \
            --oauth-service-account-email "$SA_EMAIL" \
            --max-retry-attempts=3 \
            --min-backoff=5m \
            --max-backoff=1h
    fi

done

log_info "═══════════════════════════════════════════"
log_info "Deploy completado exitosamente"
log_info ""
log_info "Imagen: ${IMAGE_TAG}"
log_info "Tag versionado: ${IMAGE_TAG_VERSIONED}"
log_info ""
log_info "Jobs creados:"
for SPIDER in $SPIDERS; do
    log_info "  - scrapper-${SPIDER}"
done
log_info ""
log_info "Ver jobs en: https://console.cloud.google.com/run/jobs?project=${PROJECT_ID}"
log_info "Ver schedulers en: https://console.cloud.google.com/cloudscheduler?project=${PROJECT_ID}"
log_info "═══════════════════════════════════════════"
