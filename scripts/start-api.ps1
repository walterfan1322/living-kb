param(
    [string]$DatabaseUrl = "postgresql+psycopg2://app_user:app_password@127.0.0.1:5432/living_kb",
    [string]$Host = "127.0.0.1",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$env:LKB_DATABASE_URL = $DatabaseUrl

uv run uvicorn living_kb.main:app --host $Host --port $Port --reload
