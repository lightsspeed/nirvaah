#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Allow SSH from this machine's current public IP.
.DESCRIPTION
    Residential ISPs rotate the address; when they do, deploy.ps1 times out on
    port 22. This reads the current address and re-applies the firewall rule
    (only port 22 changes; 80/443 stay public).
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

$ip = (Invoke-RestMethod -Uri 'https://api.ipify.org?format=json' -TimeoutSec 20).ip
Write-Host "==> Allowing SSH from $ip/32" -ForegroundColor Cyan

& terraform "-chdir=$root/infra/aws" apply -auto-approve -var "ssh_cidr=$ip/32"
if ($LASTEXITCODE -ne 0) { throw "terraform apply failed" }
