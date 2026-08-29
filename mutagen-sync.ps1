# ==========================================
# Mutagen Auto Sync Script
# Always Recreate Session
# ==========================================

$LocalPath  = "D:\All_Repos_by_as053266\insta_reel_scraper"
$RemotePath = "narcolux:~/Desktop/insta_reel_scraper"

Write-Host ""
Write-Host "Looking for existing Mutagen sessions..." -ForegroundColor Cyan

# Get all existing sync sessions
$output = mutagen sync list | Out-String
$lines = $output -split "`r?`n"

$currentId = $null
$sessions = @()

foreach ($line in $lines) {

    # Capture session identifier
    if ($line -match '^Identifier:\s*(.+)$') {
        $currentId = $matches[1].Trim()
        continue
    }

    # Capture Alpha URL
    if ($line -match '^\s*URL:\s*(.+)$') {
        $url = $matches[1].Trim()

        if ($url -eq $LocalPath -and $currentId) {
            $sessions += $currentId
        }
    }
}

# Remove duplicates
$sessions = @($sessions | Sort-Object -Unique)

# ==========================================
# Terminate existing sessions
# ==========================================

if ($sessions.Count -gt 0) {

    Write-Host ""
    Write-Host "Removing existing session(s)..." -ForegroundColor Yellow

    foreach ($session in $sessions) {
        Write-Host "  -> $session"
        mutagen sync terminate $session
    }
}
else {

    Write-Host ""
    Write-Host "No existing sessions found." -ForegroundColor Green
}

# ==========================================
# Create new session
# ==========================================

Write-Host ""
Write-Host "Creating new Mutagen session..." -ForegroundColor Cyan

mutagen sync create `
    --sync-mode=one-way-replica `
    --ignore-vcs `
    --ignore=".git" `
    --ignore=".github" `
    --ignore=".venv" `
    --ignore="venv" `
    --ignore="__pycache__" `
    --ignore=".pytest_cache" `
    --ignore=".mypy_cache" `
    --ignore=".ruff_cache" `
    --ignore=".tox" `
    --ignore=".coverage" `
    --ignore="htmlcov" `
    --ignore="*.pyc" `
    --ignore="*.pyo" `
    --ignore="*.pyd" `
    --ignore="node_modules" `
    --ignore=".next" `
    --ignore=".nuxt" `
    --ignore=".turbo" `
    --ignore=".cache" `
    --ignore="dist" `
    --ignore="build" `
    --ignore="coverage" `
    --ignore=".gradle" `
    --ignore="target" `
    --ignore="bin" `
    --ignore="obj" `
    --ignore=".idea" `
    --ignore=".vscode" `
    --ignore=".DS_Store" `
    --ignore="Thumbs.db" `
    --ignore=".env" `
    --ignore=".env.*" `
    --ignore="*.log" `
    --ignore="*.tmp" `
    --ignore="*.temp" `
    --ignore="*.bak" `
    --ignore="*.swp" `
    --ignore="*~" `
    --ignore="docker/ensure-db.sh" `
    --ignore="docker/run-dev.sh" `
    --ignore="docker/run-prod.sh" `
    --ignore="docker/run-test.sh" `
    --ignore="docker/run-lint.sh" `
    --ignore="docker/run-format.sh" `
    --default-file-mode=0644 `
    --default-directory-mode=0755 `
    "$LocalPath" `
    "$RemotePath"

# ==========================================
# Show current sessions
# ==========================================

Write-Host ""
Write-Host "Current Sessions:" -ForegroundColor Cyan

mutagen sync list

# ==========================================
# Start monitor
# ==========================================

Write-Host ""
Write-Host "Starting monitor..." -ForegroundColor Cyan

mutagen sync monitor