#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Deploy the Nirvaah stack to the Lightsail host created by infra/aws.

.DESCRIPTION
    Builds a server-side .env from the local .env (secrets never land in git),
    copies the compose files and Caddyfile to /opt/nirvaah, then pulls and
    starts the public images from Docker Hub.

    Run infra/aws first:
        terraform -chdir=infra/aws init
        terraform -chdir=infra/aws apply

.EXAMPLE
    ./deploy/deploy.ps1
    ./deploy/deploy.ps1 -AppVersion 1.1.2
#>
[CmdletBinding()]
param(
    [string]$AppVersion = "",
    [string]$FrontendTag = "",
    [switch]$SkipUpload
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$tfDir = Join-Path $root 'infra/aws'

# ── 1. Read what Terraform created ────────────────────────────────────────────
Write-Host "==> Reading terraform outputs" -ForegroundColor Cyan
$raw = & terraform "-chdir=$tfDir" output -json 2>$null
if ($LASTEXITCODE -ne 0 -or -not $raw) {
    throw "No terraform outputs. Run: terraform -chdir=infra/aws init && terraform -chdir=infra/aws apply"
}
$tf = $raw | ConvertFrom-Json
$hostName = $tf.hostname.value -replace '^https?://', ''
$ip = $tf.static_ip.value
Write-Host "    host: $hostName  ip: $ip"

# ── 2. SSH key from terraform state, written once ─────────────────────────────
$keyPath = Join-Path $env:USERPROFILE '.ssh/nirvaah-app.pem'
if (-not (Test-Path $keyPath)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $keyPath) | Out-Null
    [IO.File]::WriteAllText($keyPath, ($tf.private_key_pem.value -replace "`r`n", "`n"))
    # Windows ssh refuses keys other principals can read. Grant by SID: name
    # lookup fails on some local accounts, and a mistyped principal leaves an
    # ACE that ssh then rejects as "too open".
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    & icacls $keyPath /inheritance:r | Out-Null
    & icacls $keyPath /grant:r "*${sid}:(R)" | Out-Null
    Write-Host "==> Wrote $keyPath" -ForegroundColor Cyan
}

# ── 3. Server .env from the local .env ────────────────────────────────────────
$localEnv = @{}
Get-Content (Join-Path $root '.env') | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
        $localEnv[$matches[1]] = $matches[2].Trim()
    }
}

if (-not $FrontendTag) {
    $FrontendTag = (Get-Content (Join-Path $root 'frontend/package.json') -Raw | ConvertFrom-Json).version
}
if (-not $AppVersion) {
    # Backend and backup agent share one release line; the frontend is tagged
    # separately, so a UI-only release does not need a new API image.
    $AppVersion = if ($env:NIRVAAH_API_VERSION) { $env:NIRVAAH_API_VERSION } else { '1.1.1' }
}

$serverEnv = [ordered]@{
    APP_VERSION             = $AppVersion
    FRONTEND_TAG            = $FrontendTag
    DOCKER_NAMESPACE        = if ($localEnv.DOCKER_NAMESPACE) { $localEnv.DOCKER_NAMESPACE } else { 'lightsspeed' }
    APP_HOST                = $hostName
    ACME_EMAIL              = if ($localEnv.ACME_EMAIL) { $localEnv.ACME_EMAIL } else { "admin@$($hostName.Split('.', 2)[1])" }
    TZ                      = 'Asia/Kolkata'
    POSTGRES_DB             = if ($localEnv.POSTGRES_DB) { $localEnv.POSTGRES_DB } else { 'finance' }
    POSTGRES_USER           = if ($localEnv.POSTGRES_USER) { $localEnv.POSTGRES_USER } else { 'finance' }
    POSTGRES_PASSWORD       = $localEnv.POSTGRES_PASSWORD
    SECRET_KEY              = $localEnv.SECRET_KEY
    # No GPU box: the assistant uses the DeepSeek-compatible fallback.
    FALLBACK_BASE_URL       = if ($localEnv.FALLBACK_BASE_URL) { $localEnv.FALLBACK_BASE_URL } else { 'https://api.deepseek.com/v1' }
    FALLBACK_MODEL          = if ($localEnv.FALLBACK_MODEL) { $localEnv.FALLBACK_MODEL } else { 'deepseek-flash' }
    FALLBACK_API_KEY        = if ($localEnv.FALLBACK_API_KEY) { $localEnv.FALLBACK_API_KEY } else { $localEnv.DEEPSEEK_API_KEY }
    ASSISTANT_FALLBACK      = 'on'
    BACKUP_INTERVAL_HOURS   = if ($localEnv.BACKUP_INTERVAL_HOURS) { $localEnv.BACKUP_INTERVAL_HOURS } else { '4' }
    BACKUP_RETENTION_DAYS   = if ($localEnv.BACKUP_RETENTION_DAYS) { $localEnv.BACKUP_RETENTION_DAYS } else { '14' }
    BACKUP_RETENTION_MONTHS = if ($localEnv.BACKUP_RETENTION_MONTHS) { $localEnv.BACKUP_RETENTION_MONTHS } else { '12' }
    S3_BUCKET               = $localEnv.S3_BUCKET
    S3_PREFIX               = if ($localEnv.S3_PREFIX) { $localEnv.S3_PREFIX } else { 'nirvaah/postgres' }
    S3_ENDPOINT             = $localEnv.S3_ENDPOINT
    AWS_REGION              = if ($localEnv.AWS_REGION) { $localEnv.AWS_REGION } else { 'ap-south-1' }
    AWS_ACCESS_KEY_ID       = $localEnv.AWS_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY   = $localEnv.AWS_SECRET_ACCESS_KEY
}

$missing = $serverEnv.GetEnumerator() | Where-Object { -not $_.Value -and $_.Key -in @('POSTGRES_PASSWORD', 'SECRET_KEY') }
if ($missing) { throw "Local .env is missing: $($missing.Key -join ', ')" }

$envText = ($serverEnv.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join "`n"
$tmpEnv = Join-Path $env:TEMP 'nirvaah-server.env'
[IO.File]::WriteAllText($tmpEnv, $envText + "`n")

# ── 4. Ship the stack definition ──────────────────────────────────────────────
$sshBase = @('-i', $keyPath, '-o', 'StrictHostKeyChecking=accept-new', '-o', 'ConnectTimeout=15')
function Invoke-Remote([string]$Command) {
    & ssh @sshBase "ubuntu@$ip" $Command
    if ($LASTEXITCODE -ne 0) { throw "remote command failed ($LASTEXITCODE): $Command" }
}

Write-Host "==> Waiting for cloud-init (docker install)" -ForegroundColor Cyan
Invoke-Remote "for i in `$(seq 1 60); do docker compose version >/dev/null 2>&1 && exit 0; sleep 10; done; exit 1"

if (-not $SkipUpload) {
    Write-Host "==> Uploading compose files and .env" -ForegroundColor Cyan
    # /opt/nirvaah is created by the root-owned first-boot script.
    Invoke-Remote "sudo install -d -o ubuntu -g ubuntu -m 0755 /opt/nirvaah"
    & scp @sshBase (Join-Path $root 'docker-compose.yml') "ubuntu@${ip}:/opt/nirvaah/docker-compose.yml"
    & scp @sshBase (Join-Path $PSScriptRoot 'docker-compose.prod.yml') "ubuntu@${ip}:/opt/nirvaah/docker-compose.prod.yml"
    & scp @sshBase (Join-Path $PSScriptRoot 'Caddyfile') "ubuntu@${ip}:/opt/nirvaah/Caddyfile"
    & scp @sshBase $tmpEnv "ubuntu@${ip}:/opt/nirvaah/.env"
    if ($LASTEXITCODE -ne 0) { throw "scp failed" }
    Invoke-Remote "chmod 600 /opt/nirvaah/.env"
}
Remove-Item $tmpEnv -Force -ErrorAction SilentlyContinue

# ── 5. Start / update ─────────────────────────────────────────────────────────
Write-Host "==> Pulling images and starting the stack" -ForegroundColor Cyan
$compose = 'cd /opt/nirvaah && docker compose -f docker-compose.yml -f docker-compose.prod.yml'
Invoke-Remote "$compose pull --quiet"
Invoke-Remote "$compose up -d --remove-orphans"
Invoke-Remote "docker image prune -f >/dev/null"

# ── 6. Verify from the outside ────────────────────────────────────────────────
Write-Host "==> Waiting for TLS certificate and health" -ForegroundColor Cyan
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $res = Invoke-RestMethod -Uri "https://$hostName/api/health" -TimeoutSec 10
        if ($res.status -eq 'ok') { $ok = $true; break }
    } catch { Start-Sleep -Seconds 10 }
}
if (-not $ok) {
    Write-Warning "Health check did not pass yet. Inspect with:"
    Write-Host "  ssh -i `"$keyPath`" ubuntu@$ip `"cd /opt/nirvaah && docker compose -f docker-compose.yml -f docker-compose.prod.yml ps && docker compose logs --tail=50 caddy`""
    exit 1
}

Write-Host ""
Write-Host "Deployed: https://$hostName  (api $($res.version))" -ForegroundColor Green
Write-Host "SSH:      ssh -i `"$keyPath`" ubuntu@$ip"
