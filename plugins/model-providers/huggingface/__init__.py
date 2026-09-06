"""Hugging Face provider profile."""

import os

from providers import register_provider
from providers.base import ProviderProfile

_DEFAULT_HF_BILL_TO = "azzetco"


def _hf_default_headers() -> dict[str, str]:
    bill_to = (
        os.getenv("HF_BILL_TO")
        or os.getenv("HUGGINGFACE_BILL_TO")
        or _DEFAULT_HF_BILL_TO
    ).strip()
    return {"X-HF-Bill-To": bill_to} if bill_to else {}


huggingface = ProviderProfile(
    name="huggingface",
    aliases=("hf", "hugging-face", "huggingface-hub"),
    env_vars=("HF_TOKEN",),
    display_name="HuggingFace",
    description="HuggingFace Inference API",
    signup_url="https://huggingface.co/settings/tokens",
    fallback_models=(
        "Qwen/Qwen3.5-72B-Instruct",
        "deepseek-ai/DeepSeek-V3.2",
    ),
    base_url="https://router.huggingface.co/v1",
    default_headers=_hf_default_headers(),
)

register_provider(huggingface)
