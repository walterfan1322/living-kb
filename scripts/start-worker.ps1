param(
    [string]$DatabaseUrl = "postgresql+psycopg2://app_user:app_password@127.0.0.1:5432/living_kb"
)

$ErrorActionPreference = "Stop"
$env:LKB_DATABASE_URL = $DatabaseUrl

uv run living-kb-worker
