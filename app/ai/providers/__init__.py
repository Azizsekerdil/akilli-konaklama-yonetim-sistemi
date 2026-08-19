"""Yapay zeka saglayici adaptorleri.

Her adaptor :class:`app.ai.base.AIProvider` sozlesmesini uygular ve
saglayiciya ozgu HTTP semasini tek yerde saklar. Ust katmanlar yalnizca
:mod:`app.ai.types` yapilarini gorur.
"""

from __future__ import annotations

from app.ai.providers.anthropic import AnthropicProvider
from app.ai.providers.lmstudio import LMStudioProvider
from app.ai.providers.mock import MOCK_EMBED_MODEL, MOCK_MODEL, MockProvider
from app.ai.providers.nvidia import NvidiaProvider
from app.ai.providers.openai_compatible import OpenAICompatibleProvider

__all__ = [
    "MOCK_EMBED_MODEL",
    "MOCK_MODEL",
    "AnthropicProvider",
    "LMStudioProvider",
    "MockProvider",
    "NvidiaProvider",
    "OpenAICompatibleProvider",
]
