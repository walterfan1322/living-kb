param(
    [string]$DatabaseUrl = "postgresql+psycopg2://app_user:app_password@127.0.0.1:5432/living_kb"
)

$ErrorActionPreference = "Stop"
$env:LKB_DATABASE_URL = $DatabaseUrl

Write-Host "Starting Postgres + pgvector with docker compose..."
docker compose up -d

Write-Host "Running Alembic migrations..."
uv run alembic upgrade head

Write-Host "Bootstrap complete."
