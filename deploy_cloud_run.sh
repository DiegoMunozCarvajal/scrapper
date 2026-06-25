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

# ── Parsear flags ──
SKIP_BUILD=false
SELECTED_SPIDERS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        -s|--skip-build)
            SKIP_BUILD=true
            shift
            ;;
        -n|--spider)
            SELECTED_SPIDERS+=("$2")
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

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

# Validar estructura de queries.json
log_info "Validando queries.json..."
if ! jq empty "$QUERIES_FILE" 2>/dev/null; then
    log_error "queries.json no es JSON válido"
    exit 1
fi

for KEY in $(jq -r 'keys[]' "$QUERIES_FILE"); do
    HAS_SCHEDULE=$(jq -r ".\"$KEY\".schedule" "$QUERIES_FILE")
    HAS_CLOUD_RUN=$(jq -r ".\"$KEY\".cloud_run | type" "$QUERIES_FILE")
    QUERY_COUNT=$(jq -r ".\"$KEY\".queries | length" "$QUERIES_FILE")
    if [ "$HAS_SCHEDULE" == "null" ] || [ -z "$HAS_SCHEDULE" ]; then
        log_error "Job '$KEY' no tiene campo 'schedule'"
        exit 1
    fi
    if [ "$HAS_CLOUD_RUN" != "object" ]; then
        log_error "Job '$KEY' no tiene campo 'cloud_run'"
        exit 1
    fi
    if [ "$QUERY_COUNT" -eq 0 ] 2>/dev/null; then
        log_error "Job '$KEY' no tiene queries"
        exit 1
    fi
done
log_info "queries.json válido."

# ── Validar spiders seleccionados con -n ──
if [ ${#SELECTED_SPIDERS[@]} -gt 0 ]; then
    for SEL in "${SELECTED_SPIDERS[@]}"; do
        if ! jq -e ".\"$SEL\"" "$QUERIES_FILE" &>/dev/null; then
            log_error "Spider '$SEL' no existe en queries.json"
            exit 1
        fi
    done
    log_info "Spiders seleccionados con -n: ${SELECTED_SPIDERS[*]}"
fi

# ── Cargar .env si existe (permite sobreescribir variables del shell) ──
if [ -f "${SCRIPT_DIR}/.env" ]; then
    log_info "Cargando variables desde ${SCRIPT_DIR}/.env"
    set -a
    source "${SCRIPT_DIR}/.env"
    set +a
fi

# ── Validar variables requeridas ──
if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_KEY" ] || [ -z "$OPENAI_API_KEY" ]; then
    log_error "Faltan variables requeridas: SUPABASE_URL, SUPABASE_KEY, OPENAI_API_KEY"
    echo "Configúralas con:"
    echo "  export SUPABASE_URL=https://tu-proyecto.supabase.co"
    echo "  export SUPABASE_KEY=tu-service-role-key"
    echo "  export OPENAI_API_KEY=sk-..."
    exit 1
fi

# ── Variables opcionales: DataImpulse proxies ──
DATAIMPULSE_USER="${DATAIMPULSE_USER:-}"
DATAIMPULSE_PASSWORD="${DATAIMPULSE_PASSWORD:-}"
DATAIMPULSE_ENDPOINT="${DATAIMPULSE_ENDPOINT:-gw.dataimpulse.com}"
DATAIMPULSE_PORT="${DATAIMPULSE_PORT:-823}"

DATAIMPULSE_ENV_VARS=""
if [ -n "$DATAIMPULSE_USER" ]; then
    DATAIMPULSE_ENV_VARS="DATAIMPULSE_ENDPOINT=${DATAIMPULSE_ENDPOINT},DATAIMPULSE_PORT=${DATAIMPULSE_PORT}"
    log_info "DataImpulse proxy configurado: ${DATAIMPULSE_USER}@${DATAIMPULSE_ENDPOINT}:${DATAIMPULSE_PORT}"
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

# ── Otorgar roles necesarios a la service account (idempotente) ──
log_info "Configurando roles para la service account..."
for ROLE in roles/run.invoker roles/logging.logWriter; do
    HAS_ROLE=$(gcloud projects get-iam-policy "$PROJECT_ID" \
        --flatten="bindings[].members" \
        --format="table(bindings.role)" \
        --filter="bindings.members:serviceAccount:${SA_EMAIL} AND bindings.role:${ROLE}" \
        2>/dev/null | grep -c "$ROLE" || true)
    if [ "$HAS_ROLE" -eq 0 ]; then
        gcloud projects add-iam-policy-binding "$PROJECT_ID" \
            --member="serviceAccount:${SA_EMAIL}" \
            --role="$ROLE" \
            --condition=None \
            &>/dev/null || true
        log_info "  Rol ${ROLE} otorgado."
    else
        log_info "  Rol ${ROLE} ya existe, omitiendo."
    fi
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
if [ "$SKIP_BUILD" != true ]; then
    log_info "Autenticando Docker con Artifact Registry..."
    gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
fi

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

ensure_secret_from_file() {
    local name="$1" file="$2"
    if gcloud secrets describe "$name" --project="$PROJECT_ID" &>/dev/null; then
        gcloud secrets versions add "$name" --data-file="$file" --project="$PROJECT_ID"
        log_info "  Secret '${name}' actualizado desde archivo."
    else
        gcloud secrets create "$name" \
            --replication-policy=automatic \
            --data-file="$file" \
            --project="$PROJECT_ID"
        log_info "  Secret '${name}' creado desde archivo."
    fi
}

ensure_secret "supabase-key" "$SUPABASE_KEY"
ensure_secret "openai-api-key" "$OPENAI_API_KEY"
ensure_secret_from_file "queries-config" "$QUERIES_FILE"

if [ -n "$DATAIMPULSE_USER" ]; then
    ensure_secret "dataimpulse-user" "$DATAIMPULSE_USER"
    ensure_secret "dataimpulse-password" "$DATAIMPULSE_PASSWORD"
fi

log_info "Otorgando acceso a Secret Manager para la service account..."
ALL_SECRETS="supabase-key openai-api-key queries-config"
if [ -n "$DATAIMPULSE_USER" ]; then
    ALL_SECRETS="$ALL_SECRETS dataimpulse-user dataimpulse-password"
fi
for SECRET_NAME in $ALL_SECRETS; do
    gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="roles/secretmanager.secretAccessor" \
        --project="$PROJECT_ID" \
        &>/dev/null || true
done

# ── Build + push imagen (o skip) ──
if [ "$SKIP_BUILD" = true ]; then
    log_warn "⚠️  Modo skip-build: no se reconstruye la imagen Docker."
    log_warn "    Si cambiaste código Python, los cambios NO se aplicarán."

    log_info "Verificando imagen existente en Artifact Registry..."
    EXISTING=$(gcloud artifacts docker images list \
        "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}" \
        --filter="tags:latest" --format="value(version)" --limit=1 2>/dev/null)
    # Fallback: algunas versiones de gcloud no filtran tags correctamente
    if [ -z "$EXISTING" ]; then
        EXISTING=$(gcloud container images list-tags \
            "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}" \
            --filter="tags:latest" --format="value(digest)" --limit=1 2>/dev/null)
    fi
    if [ -z "$EXISTING" ]; then
        log_error "No se encontró imagen 'latest' en Artifact Registry."
        log_error "Ejecuta un deploy completo primero (sin --skip-build)."
        exit 1
    fi
    IMAGE_REF="$IMAGE_TAG"
    log_info "Usando imagen existente: ${IMAGE_REF}"
else
    log_info "Build de imagen Docker (puede tomar varios minutos)..."
    gcloud builds submit "${SCRIPT_DIR}" \
        --config="${SCRIPT_DIR}/cloudbuild.yaml" \
        --project="$PROJECT_ID" \
        --substitutions="_REGION=${REGION},_REPO=${REPO_NAME},_IMAGE=${IMAGE_NAME},_TAG=${VERSION_TAG}" \
        || {
            log_warn "cloudbuild.yaml falló, usando build directo..."
            cp "${SCRIPT_DIR}/Dockerfile.cloudrun" "${SCRIPT_DIR}/Dockerfile.cloudrun.tmp"
            mv "${SCRIPT_DIR}/Dockerfile" "${SCRIPT_DIR}/Dockerfile.local"
            mv "${SCRIPT_DIR}/Dockerfile.cloudrun.tmp" "${SCRIPT_DIR}/Dockerfile"
            gcloud builds submit "${SCRIPT_DIR}" \
                --tag "$IMAGE_TAG_VERSIONED" \
                --tag "$IMAGE_TAG" \
                --project="$PROJECT_ID" \
                --timeout="20m"
            mv "${SCRIPT_DIR}/Dockerfile" "${SCRIPT_DIR}/Dockerfile.cloudrun"
            mv "${SCRIPT_DIR}/Dockerfile.local" "${SCRIPT_DIR}/Dockerfile"
        }
    IMAGE_REF="$IMAGE_TAG_VERSIONED"
fi

# ── Leer spiders de queries.json ──
SPIDERS=$(jq -r 'keys[]' "$QUERIES_FILE")

if [ ${#SELECTED_SPIDERS[@]} -gt 0 ]; then
    SPIDERS="${SELECTED_SPIDERS[*]}"
fi

log_info "Spiders a procesar: $(echo $SPIDERS | tr '\n' ' ')"

# ── Construir string de secrets para jobs ──
SECRETS_STR="SUPABASE_KEY=supabase-key:latest,OPENAI_API_KEY=openai-api-key:latest,QUERIES_CONFIG=queries-config:latest"
if [ -n "$DATAIMPULSE_USER" ]; then
    SECRETS_STR="${SECRETS_STR},DATAIMPULSE_USER=dataimpulse-user:latest,DATAIMPULSE_PASSWORD=dataimpulse-password:latest"
fi

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

    # Construir lista de env vars (incluye DataImpulse si está configurado)
    ENV_VARS="SUPABASE_URL=${SUPABASE_URL}"
    if [ -n "$DATAIMPULSE_ENV_VARS" ]; then
        ENV_VARS="${ENV_VARS},${DATAIMPULSE_ENV_VARS}"
    fi

    # Crear o actualizar Cloud Run Job
    if gcloud run jobs describe "$JOB_NAME" --region="$REGION" --project="$PROJECT_ID" &>/dev/null; then
        log_info "Actualizando job existente ${JOB_NAME}..."
        gcloud run jobs update "$JOB_NAME" \
            --image "$IMAGE_REF" \
            --region "$REGION" \
            --project "$PROJECT_ID" \
            --cpu "${CPU}" \
            --memory "${MEMORY}" \
            --task-timeout "${TIMEOUT}" \
            --args "$SPIDER" \
            --set-env-vars "$ENV_VARS" \
            --set-secrets "$SECRETS_STR" \
            --max-retries 1 \
            --service-account "$SA_EMAIL" \
            --labels "spider=${SPIDER},environment=production,managed-by=deploy-script"
    else
        log_info "Creando job ${JOB_NAME}..."
        gcloud run jobs create "$JOB_NAME" \
            --image "$IMAGE_REF" \
            --region "$REGION" \
            --project "$PROJECT_ID" \
            --cpu "${CPU}" \
            --memory "${MEMORY}" \
            --task-timeout "${TIMEOUT}" \
            --args "$SPIDER" \
            --set-env-vars "$ENV_VARS" \
            --set-secrets "$SECRETS_STR" \
            --max-retries 1 \
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
            --min-backoff=30m \
            --max-backoff=2h
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
            --min-backoff=30m \
            --max-backoff=2h
    fi

done

log_info "═══════════════════════════════════════════"
log_info "Deploy completado exitosamente"
log_info ""
log_info "Imagen: ${IMAGE_REF}"
log_info ""
log_info "Jobs creados:"
for SPIDER in $SPIDERS; do
    log_info "  - scrapper-${SPIDER}"
done
log_info ""
log_info "Ver jobs en: https://console.cloud.google.com/run/jobs?project=${PROJECT_ID}"
log_info "Ver schedulers en: https://console.cloud.google.com/cloudscheduler?project=${PROJECT_ID}"
log_info "═══════════════════════════════════════════"
