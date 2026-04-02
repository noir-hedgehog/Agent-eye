# SPDX-License-Identifier: GPL-3.0-or-later
"""
Helpers aligned with Alibaba Cloud Model Studio (DashScope) Qwen3.5 / Qwen-VL
multimodal chat APIs (OpenAI-compatible).

Reference (Chinese docs, retrieved 2026):
- OpenAI Chat Completions + image_url / min_pixels / max_pixels:
  https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions
- Vision overview: https://help.aliyun.com/zh/model-studio/vision

Typical Qwen3.5 / Qwen3-VL (non–high-res mode): default max_pixels is 2_621_440;
images above that are downscaled server-side. min_pixels defaults to 65_536.
"""

from __future__ import annotations

import base64
import math
from typing import Any, Dict, Optional

# DashScope defaults for Qwen3.5 / Qwen3-VL family (vl_high_resolution_images=false)
QWEN35_DEFAULT_MAX_PIXELS = 2_621_440
QWEN35_DEFAULT_MIN_PIXELS = 65_536

# Longest edge if the image were square and exactly at default max_pixels (agent-side hint)
QWEN35_RECOMMENDED_MAX_LONGEST_EDGE = int(math.sqrt(QWEN35_DEFAULT_MAX_PIXELS))  # 1619


def recommended_max_longest_edge(max_pixels: int = QWEN35_DEFAULT_MAX_PIXELS) -> int:
    """Upper bound for the longest side to stay near DashScope default max_pixels (square ref)."""
    return int(math.sqrt(max(1, max_pixels)))


def vision_meta_preset_qwen35_plus() -> Dict[str, Any]:
    """
    Extra fields for Agent-eye vision_meta when targeting Qwen3.5-Plus / Qwen3-VL on DashScope.
    Downstream can pass images as OpenAI-style image_url (HTTPS or data: URL).
    """
    return {
        "vl_profile": "dashscope-qwen35-plus",
        "dashscope_max_pixels_default": QWEN35_DEFAULT_MAX_PIXELS,
        "dashscope_min_pixels_default": QWEN35_DEFAULT_MIN_PIXELS,
        "recommended_max_longest_edge": QWEN35_RECOMMENDED_MAX_LONGEST_EDGE,
        "openai_multimodal": {
            "content_type": "array",
            "image_part": {
                "type": "image_url",
                "image_url": {
                    "url": "<https URL or data:image/jpeg;base64,...>",
                    "detail": "optional; use min_pixels / max_pixels on image part per API",
                },
            },
            "notes": (
                "Use Chat Completions compatible endpoint; image in user message content[]. "
                "Optional keys min_pixels / max_pixels on the image part per Alibaba docs."
            ),
        },
    }


def build_data_url(image_bytes: bytes, mime: str = "image/jpeg") -> str:
    """RFC 2397 data URL for OpenAI-compatible image_url.url."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


def build_openai_user_multimodal_message(
    text: str,
    image_bytes: bytes,
    mime: str = "image/jpeg",
) -> Dict[str, Any]:
    """
    Single user message in OpenAI format: content = [ {type:text}, {type:image_url} ].
    """
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {
                "type": "image_url",
                "image_url": {"url": build_data_url(image_bytes, mime=mime)},
            },
        ],
    }


def merge_vision_meta(base: Dict[str, Any], preset: Optional[str]) -> Dict[str, Any]:
    """Merge preset hints into agent vision_meta."""
    out = dict(base)
    if preset in (None, "", "none"):
        return out
    key = preset.lower().replace("_", "-")
    if key in ("qwen35-plus", "qwen3.5-plus", "dashscope-qwen35"):
        out.update(vision_meta_preset_qwen35_plus())
    return out
