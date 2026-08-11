param(
    [string]$DestinationRoot = 'D:\Download\EchoPosture-P5\models'
)

$ErrorActionPreference = 'Stop'
$repo = 'mk-minchul/CVLface'
$ref = '308142aa50adf2e187711354f7524635d3414f1e'
$sourceRoot = 'cvlface/research/recognition/code/run_v1'

$shared = @(
    'models/__init__.py',
    'models/base/__init__.py',
    'models/base/utils.py',
    'models/base/configs/example.yaml'
)
$vit = @(
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
$ir101 = @(
    'models/iresnet/__init__.py',
    'models/iresnet/model.py',
    'models/iresnet/configs/v1_ir18.yaml',
    'models/iresnet/configs/v1_ir50.yaml',
    'models/iresnet/configs/v1_ir101.yaml'
)

function Write-GitHubFile([string]$relativePath, [string]$destination) {
    $source = "$sourceRoot/$relativePath"
    $encoded = gh api "repos/$repo/contents/$source`?ref=$ref" --jq .content
    if (-not $encoded) { throw "GitHub file content was empty: $source" }
    $bytes = [Convert]::FromBase64String(($encoded -join '').Replace("`n", '').Replace("`r", ''))
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    [IO.File]::WriteAllBytes($destination, $bytes)
}

function Write-TextFile([string]$relativePath, [string]$content, [string]$destination) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    [IO.File]::WriteAllText($destination, $content, [Text.UTF8Encoding]::new($false))
}

$vitRoot = Join-Path $DestinationRoot 'cvlface_adaface_vit_base_kprpe_webface4m'
$irRoot = Join-Path $DestinationRoot 'cvlface_adaface_ir101_webface4m'
foreach ($relativePath in $shared + $vit) {
    Write-Output "Hydrating ViT $relativePath"
    Write-GitHubFile $relativePath (Join-Path $vitRoot $relativePath)
}
foreach ($relativePath in $shared + $ir101) {
    Write-Output "Hydrating IR101 $relativePath"
    Write-GitHubFile $relativePath (Join-Path $irRoot $relativePath)
}

Write-TextFile 'config.json' @'
{
  "architectures": ["CVLFaceRecognitionModel"],
  "auto_map": {"AutoConfig": "wrapper.ModelConfig", "AutoModel": "wrapper.CVLFaceRecognitionModel"},
  "conf": {"color_space": "RGB", "freeze": false, "input_size": [3, 112, 112], "mask_ratio": 0.0, "name": "base", "output_dim": 512, "rpe_config": {"ctx_type": "rel_keypoint_splithead_unshared", "method": "product", "mode": "ctx", "name": "KPRPE_shared", "num_keypoints": 5, "ratio": 1.9, "rpe_on": "k", "shared_head": true}, "start_from": "", "yaml_path": "models/vit_kprpe/configs/v1_base_kprpe_splithead_unshared.yaml"},
  "torch_dtype": "float32",
  "transformers_version": "4.33.0"
}
'@ (Join-Path $vitRoot 'config.json')
Write-TextFile 'wrapper.py' @'
from transformers import PreTrainedModel
from transformers import PretrainedConfig
from omegaconf import OmegaConf
from models import get_model
import yaml

class ModelConfig(PretrainedConfig):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.conf = dict(yaml.safe_load(open('pretrained_model/model.yaml')))

class CVLFaceRecognitionModel(PreTrainedModel):
    config_class = ModelConfig

    def __init__(self, cfg):
        super().__init__(cfg)
        model_conf = OmegaConf.create(cfg.conf)
        self.model = get_model(model_conf)
        self.model.load_state_dict_from_path('pretrained_model/model.pt')

    def forward(self, *args, **kwargs):
        return self.model(*args, **kwargs)
'@ (Join-Path $vitRoot 'wrapper.py')
Write-TextFile 'pretrained_model/model.yaml' @'
input_size: [3, 112, 112]
color_space: 'RGB'
name: 'base'
output_dim: 512
start_from: ''
freeze: False
mask_ratio: 0.0
rpe_config:
  name: KPRPE_shared
  rpe_on: k
  shared_head: True
  mode: ctx
  method: product
  ratio: 1.9
  ctx_type: 'rel_keypoint_splithead_unshared'
  num_keypoints: 5
yaml_path: models/vit_kprpe/configs/v1_base_kprpe_splithead_unshared.yaml
'@ (Join-Path $vitRoot 'pretrained_model/model.yaml')

Write-TextFile 'config.json' @'
{
  "architectures": ["CVLFaceRecognitionModel"],
  "auto_map": {"AutoConfig": "wrapper.ModelConfig", "AutoModel": "wrapper.CVLFaceRecognitionModel"},
  "conf": {"color_space": "BGR", "freeze": false, "input_size": [3, 112, 112], "name": "ir101", "output_dim": 512, "start_from": "", "yaml_path": "models/iresnet/configs/v1_ir101.yaml"},
  "torch_dtype": "float32",
  "transformers_version": "4.33.0"
}
'@ (Join-Path $irRoot 'config.json')
Write-TextFile 'wrapper.py' @'
from transformers import PreTrainedModel
from transformers import PretrainedConfig
from omegaconf import OmegaConf
from models import get_model
import yaml

class ModelConfig(PretrainedConfig):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.conf = dict(yaml.safe_load(open('pretrained_model/model.yaml')))

class CVLFaceRecognitionModel(PreTrainedModel):
    config_class = ModelConfig

    def __init__(self, cfg):
        super().__init__(cfg)
        model_conf = OmegaConf.create(cfg.conf)
        self.model = get_model(model_conf)
        self.model.load_state_dict_from_path('pretrained_model/model.pt')

    def forward(self, *args, **kwargs):
        return self.model(*args, **kwargs)
'@ (Join-Path $irRoot 'wrapper.py')
Write-TextFile 'pretrained_model/model.yaml' @'
input_size:
- 3
- 112
- 112
color_space: RGB
name: ir101
output_dim: 512
start_from: ''
freeze: false
yaml_path: models/iresnet/configs/v1_ir101.yaml
'@ (Join-Path $irRoot 'pretrained_model/model.yaml')

Write-Output 'Model code hydration complete.'
