param(
    [string]$DestinationRoot = 'D:\Download\EchoPosture-P5\models'
)

$ErrorActionPreference = 'Stop'
$models = @(
    @{
        Name = 'cvlface_adaface_vit_base_kprpe_webface4m'
        Revision = '6530d73fb0af4d1d8287f31d559780c648ebd22a'
        Files = @(
            'README.md',
            'files.txt',
            'config.json',
            'wrapper.py',
            'model.safetensors',
            'pretrained_model/aligner.pt',
            'pretrained_model/aligner.yaml',
            'pretrained_model/config.yaml',
            'pretrained_model/model.pt',
            'pretrained_model/model.yaml',
            'models/__init__.py',
            'models/base/__init__.py',
            'models/base/utils.py',
            'models/base/configs/example.yaml',
            'models/vit_kprpe/__init__.py',
            'models/vit_kprpe/vit.py',
            'models/vit_kprpe/rpe_options.py',
            'models/vit_kprpe/configs/v1_base_kprpe_splithead_unshared.yaml',
            'models/vit_kprpe/configs/v1_small_kprpe_splithead_unshared.yaml',
            'models/vit_kprpe/RPE/__init__.py',
            'models/vit_kprpe/RPE/rpe_ops/README.md',
            'models/vit_kprpe/RPE/rpe_ops/rpe_index.cpp',
            'models/vit_kprpe/RPE/rpe_ops/rpe_index.py',
            'models/vit_kprpe/RPE/rpe_ops/rpe_index_cuda.cu',
            'models/vit_kprpe/RPE/rpe_ops/setup.py',
            'models/vit_kprpe/RPE/KPRPE/dist.py',
            'models/vit_kprpe/RPE/KPRPE/kprpe_shared.py',
            'models/vit_kprpe/RPE/KPRPE/relative_keypoints.py'
        )
    },
    @{
        Name = 'cvlface_adaface_ir101_webface4m'
        Revision = 'f2b38d9e24bfe301490d8dd081d8924b102333dd'
        Files = @(
            'README.md',
            'files.txt',
            'config.json',
            'wrapper.py',
            'model.safetensors',
            'pretrained_model/config.yaml',
            'pretrained_model/model.pt',
            'pretrained_model/model.yaml',
            'models/__init__.py',
            'models/base/__init__.py',
            'models/base/utils.py',
            'models/base/configs/example.yaml',
            'models/iresnet/__init__.py',
            'models/iresnet/model.py',
            'models/iresnet/configs/v1_ir18.yaml',
            'models/iresnet/configs/v1_ir50.yaml',
            'models/iresnet/configs/v1_ir101.yaml'
        )
    }
)

New-Item -ItemType Directory -Force -Path $DestinationRoot | Out-Null
$manifest = [System.Collections.Generic.List[object]]::new()

foreach ($model in $models) {
    $modelRoot = Join-Path $DestinationRoot $model.Name
    foreach ($relativePath in $model.Files) {
        $target = Join-Path $modelRoot $relativePath
        $parent = Split-Path -Parent $target
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        $uriPath = ($relativePath -replace '\\', '/') -replace ' ', '%20'
        $uri = "https://huggingface.co/minchul/$($model.Name)/resolve/$($model.Revision)/$uriPath?download=true"
        if (-not (Test-Path -LiteralPath $target) -or (Get-Item -LiteralPath $target).Length -eq 0) {
            Write-Output "Downloading $($model.Name)/$relativePath"
            Invoke-WebRequest -Uri $uri -OutFile $target -UseBasicParsing -MaximumRedirection 10
        } else {
            Write-Output "Keeping existing $($model.Name)/$relativePath"
        }
        $hash = Get-FileHash -LiteralPath $target -Algorithm SHA256
        $manifest.Add([pscustomobject]@{
                model = $model.Name
                revision = $model.Revision
                file = $relativePath
                sha256 = $hash.Hash.ToLowerInvariant()
                bytes = (Get-Item -LiteralPath $target).Length
                source = $uri
            })
    }
}

$manifestPath = Join-Path $DestinationRoot 'manifest.json'
$manifest | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 -Path $manifestPath
Write-Output "Wrote $manifestPath"
