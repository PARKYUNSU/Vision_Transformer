import numpy as np
import torch
import torch.nn as nn
import scipy.ndimage as ndimage

from .encoder import Encoder
from .patch_embedding import Patch_Embedding
from .utils import np2th

class Vision_Transformer(nn.Module):
    def __init__(self, config, img_size=224, num_classes=1000, in_channels=3, pretrained=False, pretrained_path=None):
        super(Vision_Transformer, self).__init__()
        self.num_classes = num_classes

        # patch embedding
        self.patch_embed = Patch_Embedding(config, img_size, in_channels)
        num_patches = self.patch_embed.num_patches

        # Cls
        self.cls_token = nn.Parameter(torch.zeros(1, 1, config.hidden_size))
        self.pos_embed = nn.Parameter(torch.zeros(1, num_patches + 1, config.hidden_size))
        self.pos_drop = nn.Dropout(config.transformer["dropout_rate"])

        # Transformer Encoder
        self.encoder = Encoder(config)

        # Classification Head
        self.head = nn.Linear(config.hidden_size, num_classes)

        self._init_weights()

        if pretrained and pretrained_path is not None:
            self.load_from(torch.load(pretrained_path, map_location="cpu"))
    
    def _init_weights(self):
        nn.init.trunc_normal_(self.pos_embed, std=0.02)
        nn.init.trunc_normal_(self.cls_token, std=0.02)
        self.apply(self._init_module)
    
    def _init_module(self, module):
        if isinstance(module, nn.Linear):
            nn.init.xavier_uniform_(module.weight)
            if module.bias is not None:
                nn.init.zeros_(module.bias)
        elif isinstance(module, nn.Conv2d):
            nn.init.kaiming_normal_(module.weight, mode="fan_out")
            if module.bias is not None:
                nn.init.zeros_(module.bias)

    def forward(self, x):
        B = x.shape[0]
        x = self.patch_embed(x) # (B, num_patches, hidden_size)

        # Cls
        cls_tokens = self.cls_token.expand(B, -1, -1)
        x = torch.cat((cls_tokens, x), dim=1) # (B, num_patches+1, hidden_size)
        x = x + self.pos_embed
        x = self.pos_drop(x)

        # Transformer Encoder
        x = self.encoder(x)

        # Classification
        cls_out = x[:, 0]
        logits = self.head(cls_out)
        return logits
    
    def load_from(self, weights):
        """
        Hugging Face pretrained weights (state_dict)를 변환하여 모델에 로드합니다.
        - convert_state_dict() 함수를 사용해 키 이름을 변환합니다.
        - head weight/bias는 CIFAR-10용으로 shape 불일치 시 재초기화합니다.
        - pos_embed(위치 임베딩)는 크기가 다르면 2D 보간을 통해 재조정합니다.
        - 나머지 파라미터는 strict=False로 로드합니다.
        """
        # 1. pretrained state_dict의 키를 변환합니다.
        converted_weights = convert_state_dict(weights)

        # 2. Head weight 처리
        if "head/kernel" in converted_weights:
            pretrained_head_weight = np2th(converted_weights["head/kernel"]).t()
            if pretrained_head_weight.shape == self.head.weight.shape:
                self.head.weight.data.copy_(pretrained_head_weight)
            else:
                print("Pretrained head weight shape mismatch. Skipping head weight load and reinitializing head.")
                nn.init.xavier_uniform_(self.head.weight)
            converted_weights.pop("head/kernel")
        else:
            print("Warning: 'head/kernel' not found, skipping head weights load.")

        if "head/bias" in converted_weights:
            pretrained_head_bias = np2th(converted_weights["head/bias"]).t()
            if pretrained_head_bias.shape == self.head.bias.shape:
                self.head.bias.data.copy_(pretrained_head_bias)
            else:
                print("Pretrained head bias shape mismatch. Skipping head bias load and reinitializing head.")
                nn.init.zeros_(self.head.bias)
            converted_weights.pop("head/bias")
        else:
            print("Warning: 'head/bias' not found, skipping head bias load.")

        # 3. Positional embedding 처리 (pos_embed)
        if "pos_embed" in converted_weights:
            posemb = np2th(converted_weights["pos_embed"])
            if posemb.size() == self.pos_embed.size():
                self.pos_embed.data.copy_(posemb)
            else:
                # 크기가 다르면 2D 보간(ndimage.zoom) 사용
                ntok_new = self.pos_embed.size(1)
                posemb_tok, posemb_grid = posemb[:, :1], posemb[0, 1:]
                gs_old = int(np.sqrt(len(posemb_grid)))
                gs_new = int(np.sqrt(ntok_new - 1))
                posemb_grid = posemb_grid.reshape(gs_old, gs_old, -1)
                zoom = (gs_new / gs_old, gs_new / gs_old, 1)
                posemb_grid = ndimage.zoom(posemb_grid, zoom, order=1)
                posemb_grid = posemb_grid.reshape(1, gs_new * gs_new, -1)
                new_posemb = np.concatenate([posemb_tok, posemb_grid], axis=1)
                self.pos_embed.data.copy_(np2th(new_posemb))
            converted_weights.pop("pos_embed")

        # 4. 나머지 파라미터를 로드 (strict=False)
        msg = self.load_state_dict(converted_weights, strict=False)
        print("Loaded weights with message:", msg)

def convert_state_dict(state_dict):
    """ 
    Hugging Face pretrained state_dict의 키들을 우리 모델의 키로 변환합니다.
    """
    new_state_dict = {}
    for k, v in state_dict.items():
        new_k = k
        # 1. embeddings 관련 키 변환
        if k.startswith("embeddings.patch_embeddings.projection"):
            new_k = k.replace("embeddings.patch_embeddings.projection", "patch_embed.proj")
        elif k.startswith("embeddings.cls_token"):
            new_k = k.replace("embeddings.cls_token", "cls_token")
        elif k.startswith("embeddings.position_embeddings"):
            new_k = k.replace("embeddings.position_embeddings", "pos_embed")
        # 2. encoder layer 관련 키 변환
        elif k.startswith("encoder.layer."):
            # 예: "encoder.layer.0.attention.attention.query.weight"
            parts = k.split(".")
            # parts[2]는 layer index
            layer_idx = parts[2]
            # 나머지 부분 변환:
            new_key_suffix = ".".join(parts[3:])
            new_key_suffix = new_key_suffix.replace("attention.attention.query", "attn.query_dense")
            new_key_suffix = new_key_suffix.replace("attention.attention.key", "attn.key_dense")
            new_key_suffix = new_key_suffix.replace("attention.attention.value", "attn.value_dense")
            new_key_suffix = new_key_suffix.replace("attention.output.dense", "attn.output_dense")
            new_key_suffix = new_key_suffix.replace("intermediate.dense", "mlp.fc1")
            new_key_suffix = new_key_suffix.replace("output.dense", "mlp.fc2")
            new_key_suffix = new_key_suffix.replace("layernorm_before", "norm1")
            new_key_suffix = new_key_suffix.replace("layernorm_after", "norm2")
            new_k = "encoder.layers." + layer_idx + "." + new_key_suffix
        # 3. pooler 관련 키는 사용하지 않으므로 건너뛰기
        elif k.startswith("pooler"):
            continue

        new_state_dict[new_k] = v
    return new_state_dict    