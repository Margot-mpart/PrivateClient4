#!/usr/bin/env bash
set -euo pipefail

# =====================================================
# PCC Platform - Google Cloud Run Deployment Script
# =====================================================
#
# Usage: ./deploy-gcp.sh [service] [options]
#   service: 'all', 'frontend', 'api', or 'worker'
#
# Examples:
#   ./deploy-gcp.sh all
#   ./deploy-gcp.sh api --project=my-project
#   ./deploy-gcp.sh frontend --region=us-east1
#
# Author: PCC Platform Team
# =====================================================

# Text formatting
BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Default configuration
PROJECT_ID=${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}
REGION=${REGION:-us-central1}
REPO_NAME=${REPO_NAME:-pcc-repo}
SERVICE_ACCOUNT=${SERVICE_ACCOUNT:-pcc-runner}
MIN_INSTANCES=${MIN_INSTANCES:-0}
MAX_INSTANCES=${MAX_INSTANCES:-10}
MEMORY=${MEMORY:-1Gi}
CPU=${CPU:-1}
TIMEOUT=${TIMEOUT:-300}
APP_ENV=${APP_ENV:-production}

# Service-specific defaults
FE_SERVICE_NAME="pcc-fe"
API_SERVICE_NAME="pcc-api"
WORKER_SERVICE_NAME="pcc-worker"
FE_PORT=80
API_PORT=8000
WORKER_PORT=8080

# Parse command-line arguments
SERVICE=$1
shift || true

# Parse options
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project=*)
      PROJECT_ID="${1#*=}"
      ;;
    --region=*)
      REGION="${1#*=}"
      ;;
    --repo=*)
      REPO_NAME="${1#*=}"
      ;;
    --service-account=*)
      SERVICE_ACCOUNT="${1#*=}"
      ;;
    --min-instances=*)
      MIN_INSTANCES="${1#*=}"
      ;;
    --max-instances=*)
      MAX_INSTANCES="${1#*=}"
      ;;
    --memory=*)
      MEMORY="${1#*=}"
      ;;
    --cpu=*)
      CPU="${1#*=}"
      ;;
    --timeout=*)
      TIMEOUT="${1#*=}"
      ;;
    --env=*)
      APP_ENV="${1#*=}"
      ;;
    --help)
      echo -e "${BOLD}PCC Platform - Google Cloud Run Deployment Script${NC}"
      echo ""
      echo "Usage: ./deploy-gcp.sh [service] [options]"
      echo "  service: 'all', 'frontend', 'api', or 'worker'"
      echo ""
      echo "Options:"
      echo "  --project=ID        Google Cloud project ID"
      echo "  --region=REGION     Google Cloud region (default: us-central1)"
      echo "  --repo=NAME         Artifact Registry repository name (default: pcc-repo)"
      echo "  --service-account=SA Service account for Cloud Run (default: pcc-runner)"
      echo "  --min-instances=N   Minimum instances (default: 0)"
      echo "  --max-instances=N   Maximum instances (default: 10)"
      echo "  --memory=SIZE       Memory allocation (default: 1Gi)"
      echo "  --cpu=COUNT         CPU allocation (default: 1)"
      echo "  --timeout=SEC       Request timeout in seconds (default: 300)"
      echo "  --env=ENV           Application environment (default: production)"
      echo "  --help              Show this help message"
      echo ""
      echo "Examples:"
      echo "  ./deploy-gcp.sh all"
      echo "  ./deploy-gcp.sh api --project=my-project"
      echo "  ./deploy-gcp.sh frontend --region=us-east1"
      exit 0
      ;;
    *)
      echo -e "${RED}Unknown option: $1${NC}" >&2
      exit 1
      ;;
  esac
  shift
done

# Validate required parameters
if [[ -z "$PROJECT_ID" ]]; then
  echo -e "${RED}Error: Project ID is required. Use --project=ID or set PROJECT_ID env var.${NC}" >&2
  exit 1
fi

if [[ -z "$SERVICE" ]]; then
  echo -e "${RED}Error: Service name is required (all, frontend, api, or worker).${NC}" >&2
  exit 1
fi

# Validate service name
if [[ "$SERVICE" != "all" && "$SERVICE" != "frontend" && "$SERVICE" != "api" && "$SERVICE" != "worker" ]]; then
  echo -e "${RED}Error: Invalid service '$SERVICE'. Must be 'all', 'frontend', 'api', or 'worker'.${NC}" >&2
  exit 1
fi

# Display configuration
echo -e "${BOLD}Deployment Configuration:${NC}"
echo -e "  Project:         ${GREEN}$PROJECT_ID${NC}"
echo -e "  Region:          ${GREEN}$REGION${NC}"
echo -e "  Repository:      ${GREEN}$REPO_NAME${NC}"
echo -e "  Service Account: ${GREEN}$SERVICE_ACCOUNT${NC}"
echo -e "  Environment:     ${GREEN}$APP_ENV${NC}"
echo -e "  Service(s):      ${GREEN}$SERVICE${NC}"
echo ""

# Function to check if Artifact Registry repository exists, create if not
check_artifact_registry() {
  echo -e "${BOLD}Checking Artifact Registry repository...${NC}"
  
  # Check if repository exists
  if ! gcloud artifacts repositories describe "$REPO_NAME" \
       --project="$PROJECT_ID" \
       --location="$REGION" &>/dev/null; then
    
    echo -e "${YELLOW}Repository '$REPO_NAME' not found. Creating...${NC}"
    
    # Create repository
    gcloud artifacts repositories create "$REPO_NAME" \
      --project="$PROJECT_ID" \
      --repository-format=docker \
      --location="$REGION" \
      --description="PCC Platform container repository"
    
    echo -e "${GREEN}Repository created successfully.${NC}"
  else
    echo -e "${GREEN}Repository '$REPO_NAME' already exists.${NC}"
  fi
}

# Function to check if service account exists, create if not
check_service_account() {
  echo -e "${BOLD}Checking service account...${NC}"
  
  # Full service account email
  local sa_email="$SERVICE_ACCOUNT@$PROJECT_ID.iam.gserviceaccount.com"
  
  # Check if service account exists
  if ! gcloud iam service-accounts describe "$sa_email" \
       --project="$PROJECT_ID" &>/dev/null; then
    
    echo -e "${YELLOW}Service account '$SERVICE_ACCOUNT' not found. Creating...${NC}"
    
    # Create service account
    gcloud iam service-accounts create "$SERVICE_ACCOUNT" \
      --project="$PROJECT_ID" \
      --display-name="PCC Cloud Run Service Account"
    
    # Grant necessary roles
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member="serviceAccount:$sa_email" \
      --role="roles/run.admin"
    
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member="serviceAccount:$sa_email" \
      --role="roles/secretmanager.secretAccessor"
    
    echo -e "${GREEN}Service account created and configured successfully.${NC}"
  else
    echo -e "${GREEN}Service account '$SERVICE_ACCOUNT' already exists.${NC}"
  fi
}

# Function to build and deploy a service
deploy_service() {
  local service_type=$1
  local service_name
  local dockerfile_path
  local container_port
  local concurrency
  local cpu_boost
  local min_inst
  local max_inst
  
  # Set service-specific parameters
  case "$service_type" in
    frontend)
      service_name="$FE_SERVICE_NAME"
      dockerfile_path="frontend/Dockerfile"
      container_port="$FE_PORT"
      concurrency=80
      cpu_boost="true"
      min_inst="$MIN_INSTANCES"
      max_inst="$MAX_INSTANCES"
      ;;
    api)
      service_name="$API_SERVICE_NAME"
      dockerfile_path="backend/Dockerfile"
      container_port="$API_PORT"
      concurrency=30
      cpu_boost="true"
      min_inst=1  # API should always have at least one instance
      max_inst="$MAX_INSTANCES"
      ;;
    worker)
      service_name="$WORKER_SERVICE_NAME"
      dockerfile_path="worker/Dockerfile"
      container_port="$WORKER_PORT"
      concurrency=10
      cpu_boost="false"
      min_inst="$MIN_INSTANCES"
      max_inst="$MAX_INSTANCES"
      ;;
    *)
      echo -e "${RED}Error: Unknown service type '$service_type'.${NC}" >&2
      return 1
      ;;
  esac
  
  # Full image path in Artifact Registry
  local image_path="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/$service_name:latest"
  
  echo -e "\n${BOLD}Deploying $service_type service ($service_name)...${NC}"
  
  # Check if Dockerfile exists
  if [[ ! -f "$dockerfile_path" ]]; then
    echo -e "${RED}Error: Dockerfile not found at '$dockerfile_path'.${NC}" >&2
    return 1
  fi
  
  # Build and push Docker image
  echo -e "${YELLOW}Building and pushing Docker image...${NC}"
  
  # Configure Docker to use gcloud credentials
  gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet
  
  # Build image
  docker build -t "$image_path" \
    --build-arg APP_ENV="$APP_ENV" \
    -f "$dockerfile_path" .
  
  # Push image
  docker push "$image_path"
  
  echo -e "${GREEN}Image built and pushed successfully.${NC}"
  
  # Deploy to Cloud Run
  echo -e "${YELLOW}Deploying to Cloud Run...${NC}"
  
  # Prepare secrets configuration
  local secrets_config=""
  
  # Common secrets for all services
  secrets_config+=" --set-secrets=APP_ENV=app-env:latest"
  
  # Service-specific secrets
  case "$service_type" in
    frontend)
      secrets_config+=" --set-secrets=API_URL=api-url:latest"
      ;;
    api)
      secrets_config+=" --set-secrets=MONGODB_URI=mongodb-uri:latest"
      secrets_config+=" --set-secrets=JWT_SECRET=jwt-secret:latest"
      secrets_config+=" --set-secrets=STRIPE_SECRET_KEY=stripe-secret-key:latest"
      secrets_config+=" --set-secrets=FRONTEND_URL=frontend-url:latest"
      ;;
    worker)
      secrets_config+=" --set-secrets=MONGODB_URI=mongodb-uri:latest"
      secrets_config+=" --set-secrets=JWT_SECRET=jwt-secret:latest"
      secrets_config+=" --set-secrets=OPENAI_API_KEY=openai-api-key:latest"
      ;;
  esac
  
  # Deploy to Cloud Run
  gcloud run deploy "$service_name" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --image="$image_path" \
    --platform=managed \
    --port="$container_port" \
    --service-account="$SERVICE_ACCOUNT@$PROJECT_ID.iam.gserviceaccount.com" \
    --memory="$MEMORY" \
    --cpu="$CPU" \
    --concurrency="$concurrency" \
    --timeout="${TIMEOUT}s" \
    --min-instances="$min_inst" \
    --max-instances="$max_inst" \
    --cpu-boost="$cpu_boost" \
    $secrets_config \
    --allow-unauthenticated
  
  echo -e "${GREEN}Service '$service_name' deployed successfully.${NC}"
  
  # Get service URL
  local service_url=$(gcloud run services describe "$service_name" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --format='value(status.url)')
  
  echo -e "${BOLD}Service URL:${NC} ${GREEN}$service_url${NC}"
  
  # For frontend service, update the frontend-url secret
  if [[ "$service_type" == "frontend" ]]; then
    echo -e "${YELLOW}Updating frontend-url secret...${NC}"
    
    # Check if secret exists, create or update
    if ! gcloud secrets describe frontend-url --project="$PROJECT_ID" &>/dev/null; then
      echo -n "$service_url" | gcloud secrets create frontend-url \
        --project="$PROJECT_ID" \
        --replication-policy=automatic \
        --data-file=-
    else
      echo -n "$service_url" | gcloud secrets versions add frontend-url \
        --project="$PROJECT_ID" \
        --data-file=-
    fi
    
    echo -e "${GREEN}frontend-url secret updated.${NC}"
  fi
  
  # For API service, update the api-url secret
  if [[ "$service_type" == "api" ]]; then
    echo -e "${YELLOW}Updating api-url secret...${NC}"
    
    # Check if secret exists, create or update
    if ! gcloud secrets describe api-url --project="$PROJECT_ID" &>/dev/null; then
      echo -n "$service_url" | gcloud secrets create api-url \
        --project="$PROJECT_ID" \
        --replication-policy=automatic \
        --data-file=-
    else
      echo -n "$service_url" | gcloud secrets versions add api-url \
        --project="$PROJECT_ID" \
        --data-file=-
    fi
    
    echo -e "${GREEN}api-url secret updated.${NC}"
  fi
  
  return 0
}

# Main deployment logic
main() {
  # Enable required APIs
  echo -e "${BOLD}Enabling required GCP APIs...${NC}"
  gcloud services enable run.googleapis.com \
    artifactregistry.googleapis.com \
    secretmanager.googleapis.com \
    cloudbuild.googleapis.com \
    --project="$PROJECT_ID"
  
  # Check/create Artifact Registry repository
  check_artifact_registry
  
  # Check/create service account
  check_service_account
  
  # Deploy services based on the specified service
  case "$SERVICE" in
    all)
      deploy_service frontend
      deploy_service api
      deploy_service worker
      ;;
    frontend)
      deploy_service frontend
      ;;
    api)
      deploy_service api
      ;;
    worker)
      deploy_service worker
      ;;
  esac
  
  echo -e "\n${BOLD}${GREEN}Deployment completed successfully!${NC}"
  
  # Print next steps
  echo -e "\n${BOLD}Next steps:${NC}"
  echo -e "1. Verify the services are running correctly:"
  echo -e "   ${YELLOW}gcloud run services list --project=$PROJECT_ID --region=$REGION${NC}"
  echo -e "2. Check logs if needed:"
  echo -e "   ${YELLOW}gcloud logging read 'resource.type=cloud_run_revision AND resource.labels.service_name=pcc-api' --project=$PROJECT_ID --limit=10${NC}"
  echo -e "3. Set up domain mapping (if needed):"
  echo -e "   ${YELLOW}gcloud run domain-mappings create --service=$FE_SERVICE_NAME --domain=app.yourdomain.com --region=$REGION --project=$PROJECT_ID${NC}"
}

# Run the main function
main
