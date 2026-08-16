<#
.SYNOPSIS
    fetch_pose_models_mirror.ps1 的中文本地化版本，适用于访问 GitHub release
    较慢或不可达的网络环境。行为与英文版完全一致，仅界面文字为中文。

.DESCRIPTION
    与官方源脚本目的、结果完全相同：安装 EchoPosture 标准模式与专业 Beta
    模式所需的 Ultralytics YOLO26 姿态权重。GA-2.0 发行包不包含模型权重。

    兼容模式不需要运行本脚本。标准模式与专业 Beta 模式则必须运行。

    与官方脚本唯一的区别在于传输路径。每个镜像只是官方 GitHub 发布资产的
    透传代理，每个文件仍然与取自官方源的同一份固定 SHA-256 进行校验。
    返回不同字节内容的镜像会被拒绝，因此使用镜像并不会降低完整性保证。
    镜像为无关第三方运营的服务，可能随时失效；官方脚本始终是权威路径。

.PARAMETER Tier
    Standard（默认）、Professional 或 All。参见 fetch_pose_models_zh.ps1。

.PARAMETER DestinationRoot
    目标目录。默认为 <包根目录>\models\pose。

.PARAMETER Mirror
    强制使用某一个指定镜像，而不是按顺序依次尝试。

.PARAMETER Yes
    跳过交互式 Y/N 确认，直接执行。用于脚本化或 CI 场景；手动运行建议交互确认。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\tools\fetch_pose_models\fetch_pose_models_mirror_zh.ps1

.NOTES
    许可证：下载的权重受 Ultralytics 发布的 AGPL-3.0 约束
    （https://www.ultralytics.com/license），与本脚本本身的许可证无关。
#>
param(
    [ValidateSet('Standard', 'Professional', 'All')]
    [string]$Tier = 'Standard',
    [string]$DestinationRoot,
    [string]$Mirror,
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-FaceModelNotice {
    # EchoPosture 无法再分发 CVLFace P5 人脸身份识别模型：其训练数据集
    # （WebFace4M）限定仅供学术研究使用，且未经许可禁止再分发。此提示必须
    # 完整显示、不得跳过，以免用户在人脸功能不生效时毫无头绪。
    $lines = @(
        '本项目不提供人脸身份识别模型',
        '',
        '本脚本只获取姿态检测权重。EchoPosture 不下载、不镜像、也不再分发',
        'CVLFace 人脸身份识别模型（P5）。其训练数据集条款禁止未经许可的再分发。',
        '',
        '如需使用人脸身份识别功能，请自行从官方渠道获取相应模型，',
        '并放入以下位置：',
        '  models\p5\cvlface_adaface_ir101_webface4m\',
        '  models\p5\cvlface_adaface_vit_base_kprpe_webface4m\',
        '',
        '官方渠道（Hugging Face）：',
        '  https://huggingface.co/minchul/cvlface_adaface_ir101_webface4m',
        '  https://huggingface.co/minchul/cvlface_adaface_vit_base_kprpe_webface4m',
        '',
        '若不放入这些模型，人脸身份追踪功能将无法工作，',
        '应用程序也就相当于无法正常使用。'
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
$OfficialBase = "https://github.com/ultralytics/assets/releases/download/$ReleaseTag"

# 上面官方资产的透传代理。可达性已于 2026-08-15 核实；经 ghfast.top 下载的
# yolo26n-pose.pt 与官方版本逐字节一致。官方地址作为最后的兜底选项保留。
$Mirrors = @(
    [pscustomobject]@{ Name = 'ghfast.top';   Prefix = 'https://ghfast.top/' },
    [pscustomobject]@{ Name = 'gh-proxy.com'; Prefix = 'https://gh-proxy.com/' },
    [pscustomobject]@{ Name = 'github.com';   Prefix = '' }
)

if ($PSBoundParameters.ContainsKey('Mirror') -and -not [string]::IsNullOrWhiteSpace($Mirror)) {
    $Mirrors = @($Mirrors | Where-Object { $_.Name -eq $Mirror })
    if ($Mirrors.Count -eq 0) {
        throw "未知镜像 '$Mirror'。可用镜像：ghfast.top、gh-proxy.com、github.com"
    }
}

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
Write-Host 'EchoPosture 姿态模型下载器（镜像源，中文版）' -ForegroundColor Cyan
Write-Host "  上游源   : $OfficialBase"
Write-Host "  镜像列表 : $(($Mirrors | ForEach-Object { $_.Name }) -join ', ')"
Write-Host "  目标目录 : $DestinationRoot"
Write-Host "  档位     : $Tier"
Write-Host ''
Write-Host '下载的权重由 Ultralytics 以 AGPL-3.0 许可证发布。' -ForegroundColor Yellow
Write-Host '完整条款见 https://www.ultralytics.com/license 。' -ForegroundColor Yellow
Write-Host '镜像为第三方代理服务。每个文件仍会与官方 SHA-256 校验，' -ForegroundColor Yellow
Write-Host '任何不一致都会被丢弃。' -ForegroundColor Yellow
Write-Host ''

Write-FaceModelNotice

if (-not $Yes) {
    $response = Read-Host '是否继续下载以上权重？[y/N]'
    if ($response -notmatch '^(?i:y|yes)$') {
        Write-Host ''
        Write-Host '已取消：未下载任何文件。' -ForegroundColor Yellow
        exit 1
    }
}

function Get-Sha256([string]$Path) {
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$selected = $Catalog | Where-Object { $_.Tiers -contains $Tier }
if (-not $selected) {
    throw "档位 '$Tier' 没有对应的权重。"
}

$failures = @()
foreach ($item in $selected) {
    $target = Join-Path $DestinationRoot $item.Name

    if (Test-Path -LiteralPath $target) {
        if ((Get-Sha256 $target) -eq $item.Sha256) {
            Write-Host "[ok]      $($item.Name) 已存在且校验通过。" -ForegroundColor Green
            continue
        }
        Write-Host "[replace] $($item.Name) 已存在但哈希不匹配，将重新下载。" -ForegroundColor Yellow
    }

    $sizeMb = [math]::Round($item.Bytes / 1MB, 1)
    $installed = $false
    $hadInvalidExisting = Test-Path -LiteralPath $target
    $attempts = @()

    foreach ($source in $Mirrors) {
        $uri = "$($source.Prefix)$OfficialBase/$($item.Name)"
        $temp = "$target.partial"
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }

        Write-Host "[get]     $($item.Name)（$sizeMb MB），通过 $($source.Name) ..."
        try {
            $previous = $ProgressPreference
            $ProgressPreference = 'SilentlyContinue'
            try {
                Invoke-WebRequest -Uri $uri -OutFile $temp -UseBasicParsing -MaximumRedirection 10
            } finally {
                $ProgressPreference = $previous
            }
        } catch {
            if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
            $attempts += "$($source.Name)：$($_.Exception.Message)"
            Write-Host "[skip]    $($source.Name) 失败，尝试下一个来源。" -ForegroundColor Yellow
            continue
        }

        $actualBytes = (Get-Item -LiteralPath $temp).Length
        $actualHash = Get-Sha256 $temp
        if ($actualBytes -ne $item.Bytes -or $actualHash -ne $item.Sha256) {
            Remove-Item -LiteralPath $temp -Force
            $attempts += "$($source.Name)：完整性不匹配（实际 $actualBytes 字节，sha256 $actualHash）"
            Write-Host "[reject]  $($source.Name) 返回了非预期内容，已丢弃。" -ForegroundColor Red
            continue
        }

        Move-Item -LiteralPath $temp -Destination $target -Force
        Write-Host "[ok]      $($item.Name) 校验通过（来自 $($source.Name)）。" -ForegroundColor Green
        $installed = $true
        break
    }

    if (-not $installed) {
        # 若未校验的权重残留在磁盘上，应用会加载它并在后端深处失败，
        # 而不是给出清晰的"模型缺失"提示。
        if ($hadInvalidExisting -and (Test-Path -LiteralPath $target)) {
            Remove-Item -LiteralPath $target -Force
            Write-Host "[clean]   已移除未校验通过的旧 $($item.Name)。" -ForegroundColor Yellow
        }
        $failures += "$($item.Name)：所有来源均失败 -> $($attempts -join ' | ')"
        Write-Host "[fail]    $($item.Name) 未能从任何来源安装。" -ForegroundColor Red
    }
}

Write-Host ''
$exitCode = 0
if ($failures.Count -gt 0) {
    Write-Host '以下权重未能安装：' -ForegroundColor Red
    foreach ($failure in $failures) { Write-Host "  - $failure" -ForegroundColor Red }
    $exitCode = 1
} else {
    Write-Host '所有请求的权重均已安装并校验通过。' -ForegroundColor Green
    Write-Host '现在可以启动 EchoPosture，并选择标准模式或专业 Beta 模式。'
}

Write-FaceModelNotice
exit $exitCode
