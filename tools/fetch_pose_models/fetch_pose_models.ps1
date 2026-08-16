<#
.SYNOPSIS
    Downloads the Ultralytics YOLO26 pose weights required by EchoPosture
    Standard and Professional Beta modes, from the official GitHub source.

.DESCRIPTION
    GA-2.0 is distributed WITHOUT model weights. The Ultralytics YOLO26 weights
    are AGPL-3.0 licensed and each user obtains them directly from the upstream
    publisher, so this script never mirrors or re-hosts them.

    Compatibility mode does NOT need this script. Standard mode and
    Professional Beta mode DO.

    Every file is verified against a pinned SHA-256 before it is accepted.

.PARAMETER Tier
    Which weights to fetch.
      Standard     - yolo26n-pose.pt only (7.9 MB). Default.
      Professional - yolo26l-pose.pt and yolo26x-pose.pt (184 MB total).
      All          - every weight above.

.PARAMETER DestinationRoot
    Target directory. Defaults to <package root>\models\pose, which is where
    EchoPosture looks by default.

.PARAMETER Yes
    Skip the interactive Y/N confirmation and proceed immediately. For scripted
    or CI use; manual runs should confirm interactively.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\tools\fetch_pose_models\fetch_pose_models.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\tools\fetch_pose_models\fetch_pose_models.ps1 -Tier All

.NOTES
    License: the downloaded weights are governed by AGPL-3.0 as published by
    Ultralytics (https://www.ultralytics.com/license), not by this script.
#>
param(
    [ValidateSet('Standard', 'Professional', 'All')]
    [string]$Tier = 'Standard',
    [string]$DestinationRoot,
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-FaceModelNotice {
    # EchoPosture cannot redistribute the CVLFace P5 face-identity models: their
    # training dataset (WebFace4M) restricts use to academic research and forbids
    # redistribution without permission. This notice must be shown, not skipped,
    # so users are never left wondering why face identity features do nothing.
    $lines = @(
        'FACE IDENTITY MODELS ARE NOT PROVIDED BY THIS PROJECT',
        '',
        'This script only fetches pose-detection weights. EchoPosture does not',
        'download, mirror, or redistribute the CVLFace face-identity models',
        '(P5). Their training dataset forbids redistribution without permission.',
        '',
        'To use face identity features, obtain the models yourself from the',
        'official source and place them at:',
        '  models\p5\cvlface_adaface_ir101_webface4m\',
        '  models\p5\cvlface_adaface_vit_base_kprpe_webface4m\',
        '',
        'Official source (Hugging Face):',
        '  https://huggingface.co/minchul/cvlface_adaface_ir101_webface4m',
        '  https://huggingface.co/minchul/cvlface_adaface_vit_base_kprpe_webface4m',
        '',
        'WITHOUT these models, face identity tracking will not function, and the',
        'application is effectively unusable for its core purpose.'
    )
    $width = ($lines | Measure-Object -Property Length -Maximum).Maximum
    $border = '#' * ($width + 4)
    Write-Host ''
    Write-Host $border -ForegroundColor Red
    foreach ($line in $lines) {
        Write-Host ('# ' + $line.PadRight($width) + ' #') -ForegroundColor Red
    }
    Write-Host $border -ForegroundColor Red
    Write-Host ''
}

$ReleaseTag = 'v8.4.0'
$BaseUri = "https://github.com/ultralytics/assets/releases/download/$ReleaseTag"

# Pinned upstream identities, verified against the Ultralytics assets release
# API on 2026-08-15. A mismatch means the file is not the audited weight.
$Catalog = @(
    [pscustomobject]@{
        Name   = 'yolo26n-pose.pt'
        Tiers  = @('Standard', 'All')
        Bytes  = 7878574
        Sha256 = 'eb3bb8268828aeaf515cec23a4bfafd793944a86fe9af94ba7823609c14522a9'
    },
    [pscustomobject]@{
        Name   = 'yolo26l-pose.pt'
        Tiers  = @('Professional', 'All')
        Bytes  = 57995961
        Sha256 = 'ad33da8a29ea5772318c4c980844e47b56792d2b63815ad4e8e09c078c7d1abf'
    },
    [pscustomobject]@{
        Name   = 'yolo26x-pose.pt'
        Tiers  = @('Professional', 'All')
        Bytes  = 126242553
        Sha256 = '08ed9e01d22a6f248b04f2f9992016aca9a32250b9ab57057d886a09d026700d'
    }
)

if ([string]::IsNullOrWhiteSpace($DestinationRoot)) {
    $DestinationRoot = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'models\pose'
}
$DestinationRoot = [IO.Path]::GetFullPath($DestinationRoot)
New-Item -ItemType Directory -Force -Path $DestinationRoot | Out-Null

Write-Host ''
Write-Host 'EchoPosture pose model downloader (official source)' -ForegroundColor Cyan
Write-Host "  Source      : $BaseUri"
Write-Host "  Destination : $DestinationRoot"
Write-Host "  Tier        : $Tier"
Write-Host ''
Write-Host 'The downloaded weights are published by Ultralytics under AGPL-3.0.' -ForegroundColor Yellow
Write-Host 'See https://www.ultralytics.com/license for the terms that govern them.' -ForegroundColor Yellow
Write-Host ''

Write-FaceModelNotice

if (-not $Yes) {
    $response = Read-Host 'Proceed with downloading the weights listed above? [y/N]'
    if ($response -notmatch '^(?i:y|yes)$') {
        Write-Host ''
        Write-Host 'Aborted: nothing was downloaded.' -ForegroundColor Yellow
        exit 1
    }
}

function Get-Sha256([string]$Path) {
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$selected = $Catalog | Where-Object { $_.Tiers -contains $Tier }
if (-not $selected) {
    throw "No weights are mapped to tier '$Tier'."
}

$failures = @()
foreach ($item in $selected) {
    $target = Join-Path $DestinationRoot $item.Name
    $hadInvalidExisting = $false

    if (Test-Path -LiteralPath $target) {
        if ((Get-Sha256 $target) -eq $item.Sha256) {
            Write-Host "[ok]      $($item.Name) already present and verified." -ForegroundColor Green
            continue
        }
        $hadInvalidExisting = $true
        Write-Host "[replace] $($item.Name) exists but does not match the pinned hash; re-downloading." -ForegroundColor Yellow
    }

    # An unverified weight left on disk would be loaded by the app and fail deep
    # inside the backend instead of reporting a missing model.
    $temp = "$target.partial"
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }

    $sizeMb = [math]::Round($item.Bytes / 1MB, 1)
    Write-Host "[get]     $($item.Name) ($sizeMb MB) ..."
    try {
        $previous = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'
        try {
            Invoke-WebRequest -Uri "$BaseUri/$($item.Name)" -OutFile $temp `
                -UseBasicParsing -MaximumRedirection 10
        } finally {
            $ProgressPreference = $previous
        }
    } catch {
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
        if ($hadInvalidExisting -and (Test-Path -LiteralPath $target)) {
            Remove-Item -LiteralPath $target -Force
            Write-Host "[clean]   Removed the unverified existing $($item.Name)." -ForegroundColor Yellow
        }
        $failures += "$($item.Name): download failed - $($_.Exception.Message)"
        Write-Host "[fail]    $($item.Name) could not be downloaded." -ForegroundColor Red
        continue
    }

    $actualBytes = (Get-Item -LiteralPath $temp).Length
    $actualHash = Get-Sha256 $temp
    if ($actualBytes -ne $item.Bytes -or $actualHash -ne $item.Sha256) {
        Remove-Item -LiteralPath $temp -Force
        if ($hadInvalidExisting -and (Test-Path -LiteralPath $target)) {
            Remove-Item -LiteralPath $target -Force
            Write-Host "[clean]   Removed the unverified existing $($item.Name)." -ForegroundColor Yellow
        }
        $failures += "$($item.Name): integrity check failed (got $actualBytes bytes, sha256 $actualHash)"
        Write-Host "[fail]    $($item.Name) failed verification and was discarded." -ForegroundColor Red
        continue
    }

    Move-Item -LiteralPath $temp -Destination $target -Force
    Write-Host "[ok]      $($item.Name) verified." -ForegroundColor Green
}

Write-Host ''
$exitCode = 0
if ($failures.Count -gt 0) {
    Write-Host 'Some weights were not installed:' -ForegroundColor Red
    foreach ($failure in $failures) { Write-Host "  - $failure" -ForegroundColor Red }
    Write-Host ''
    Write-Host 'If GitHub is unreachable from your network, try the mirror variant:' -ForegroundColor Yellow
    Write-Host '  tools\fetch_pose_models\fetch_pose_models_mirror.ps1' -ForegroundColor Yellow
    $exitCode = 1
} else {
    Write-Host 'All requested weights are installed and verified.' -ForegroundColor Green
    Write-Host 'You can now start EchoPosture and select Standard or Professional Beta mode.'
}

Write-FaceModelNotice
exit $exitCode
