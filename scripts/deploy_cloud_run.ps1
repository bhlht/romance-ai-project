$PROJECT_ID = "romance-ai-creator" # Update if different
$REGION = "asia-southeast1" # Singapore (Supports L4 GPU)
$SERVICE_NAME = "romance-ai-backend"
$IMAGE_NAME = "gcr.io/$PROJECT_ID/$SERVICE_NAME"

# 1. Enable Services (First time only)
# gcloud services enable run.googleapis.com
# gcloud services enable cloudbuild.googleapis.com

$GCLOUD = "C:\Users\manager\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"

# 2. Build Image
Write-Host "🚧 Building Container Image..."
& $GCLOUD builds submit --tag $IMAGE_NAME --project $PROJECT_ID .

# 3. Deploy to Cloud Run
Write-Host "🚀 Deploying to Cloud Run (GPU L4)..."

# Load secrets from .env if possible, otherwise user must ensure they are set or passed manualy
# For simplicity, we assume standard env vars or user inputs them. 
# Here we will try to read from local .env for convenience.

$EnvFile = ".env"
$HF_TOKEN = ""
$GEMINI_API_KEY = ""
$PG_HOST = ""
$PG_PORT = ""
$PG_DATABASE = ""
$PG_USER = ""
$PG_PASSWORD = ""
$DB_SSL = ""

if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match "HF_TOKEN=(.*)") { $HF_TOKEN = $matches[1].Trim() }
        if ($_ -match "GEMINI_API_KEY=(.*)") { $GEMINI_API_KEY = $matches[1].Trim() }
        if ($_ -match "PG_HOST=(.*)") { $PG_HOST = $matches[1].Trim() }
        if ($_ -match "PG_PORT=(.*)") { $PG_PORT = $matches[1].Trim() }
        if ($_ -match "PG_DATABASE=(.*)") { $PG_DATABASE = $matches[1].Trim() }
        if ($_ -match "PG_USER=(.*)") { $PG_USER = $matches[1].Trim() }
        if ($_ -match "PG_PASSWORD=(.*)") { $PG_PASSWORD = $matches[1].Trim() }
        if ($_ -match "DB_SSL=(.*)") { $DB_SSL = $matches[1].Trim() }
    }
}

if ([string]::IsNullOrEmpty($HF_TOKEN)) {
    Write-Host "⚠️ HF_TOKEN not found in .env. Model download might fail."
}

& $GCLOUD run deploy $SERVICE_NAME `
    --image $IMAGE_NAME `
    --project $PROJECT_ID `
    --platform managed `
    --region $REGION `
    --allow-unauthenticated `
    --port 8080 `
    --gpu 1 `
    --gpu-type nvidia-l4 `
    --no-cpu-throttling `
    --memory 32Gi `
    --cpu 8 `
    --timeout 3600 `
    --set-env-vars "HF_TOKEN=${HF_TOKEN},GEMINI_API_KEY=${GEMINI_API_KEY},MOCK_MODE=False,PG_HOST=${PG_HOST},PG_PORT=${PG_PORT},PG_DATABASE=${PG_DATABASE},PG_USER=${PG_USER},PG_PASSWORD=${PG_PASSWORD},DB_SSL=${DB_SSL}"

Write-Host "✅ Deployment Complete!"
