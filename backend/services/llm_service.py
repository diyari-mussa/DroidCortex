"""
DroidCortex — LLM Service.
Abstracted interface for multiple AI/LLM providers (OpenAI, Anthropic, Google).
Used by the AI Agent executor for exploratory testing.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Optional

import structlog

from backend.config import settings

logger = structlog.get_logger(__name__)


# ── System Prompt ──────────────────────────────────────────────

SYSTEM_PROMPT = """You are DroidCortex AI Agent — an expert Android app tester.

You are testing an Android app on a real device. You receive the current device state (UI hierarchy XML, screenshot description, logcat) and must decide the next testing action.

AVAILABLE ACTIONS (respond with exactly one):
- tap(x, y) — Tap at screen coordinates
- input_text(text) — Type text into the focused input field
- swipe(x1, y1, x2, y2) — Swipe gesture
- press_back() — Press the Back button
- press_home() — Press the Home button
- press_key(keycode) — Press a key by keycode (66=ENTER, 67=DEL)
- wait(seconds) — Wait for a specified duration
- assert_text_visible(text) — Verify text is visible on screen
- send_broadcast(action, extras) — Send an Android broadcast intent
- shell(command) — Execute a shell command on the device
- screenshot() — Take a screenshot for inspection
- done(verdict, summary) — Testing is complete. verdict must be "pass" or "fail"

RESPONSE FORMAT (strict JSON):
{
    "reasoning": "Brief explanation of why you're taking this action",
    "action": "action_name",
    "params": { ... action-specific parameters ... },
    "confidence": 0.0-1.0
}

RULES:
1. Always analyze the UI hierarchy XML to understand what's on screen
2. Look at element bounds to determine tap coordinates (use center of element)
3. Test the app systematically — try different features, inputs, navigation
4. If you detect a crash or ANR, report it immediately with done(verdict="fail")
5. If you get stuck in a loop (same screen > 3 times), try a different approach
6. Maximum steps will be enforced — be efficient
7. When you've sufficiently tested the goal, call done() with your verdict
"""


# ── Provider Interface ─────────────────────────────────────────


class LLMProvider(ABC):
    """Abstract base for LLM providers."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """Send a chat request and return the parsed JSON response.
        Returns dict with: reasoning, action, params, confidence
        """
        ...

    @abstractmethod
    def chat_with_vision(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """Chat request with image/vision support."""
        ...

    def _parse_response(self, text: str) -> dict[str, Any]:
        """Parse the LLM response text into a structured dict."""
        text = text.strip()

        # Try to extract JSON from the response
        # Handle markdown code blocks
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON-like content in the text
            import re
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

            logger.warning("llm_parse_failed", text=text[:200])
            return {
                "reasoning": text,
                "action": "wait",
                "params": {"seconds": 2},
                "confidence": 0.1,
            }


# ── OpenAI Provider ────────────────────────────────────────────


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str | None = None, model: str = "gpt-4o"):
        self.model = model
        try:
            import openai
            self.client = openai.OpenAI(api_key=api_key or settings.openai_api_key)
        except ImportError:
            raise ImportError("openai package not installed. Run: pip install openai")

    def chat(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        all_messages = []
        if system_prompt:
            all_messages.append({"role": "system", "content": system_prompt})
        all_messages.extend(messages)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=all_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            return self._parse_response(response.choices[0].message.content)
        except Exception as exc:
            logger.error("openai_error", error=str(exc))
            raise

    def chat_with_vision(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        # OpenAI vision uses the same API, images go in content array
        return self.chat(messages, system_prompt, temperature, max_tokens)


# ── Anthropic Provider ─────────────────────────────────────────


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-20250514"):
        self.model = model
        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key)
        except ImportError:
            raise ImportError("anthropic package not installed. Run: pip install anthropic")

    def chat(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        try:
            response = self.client.messages.create(
                model=self.model,
                system=system_prompt or SYSTEM_PROMPT,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return self._parse_response(response.content[0].text)
        except Exception as exc:
            logger.error("anthropic_error", error=str(exc))
            raise

    def chat_with_vision(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        return self.chat(messages, system_prompt, temperature, max_tokens)


# ── Google Gemini Provider ─────────────────────────────────────


class GoogleProvider(LLMProvider):
    def __init__(self, api_key: str | None = None, model: str = "gemini-pro"):
        self.model = model
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key or settings.google_api_key)
            self.genai = genai
        except ImportError:
            raise ImportError("google-generativeai package not installed. Run: pip install google-generativeai")

    def chat(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        try:
            model = self.genai.GenerativeModel(
                self.model,
                system_instruction=system_prompt or SYSTEM_PROMPT,
            )

            # Convert messages to Gemini format
            history = []
            for msg in messages[:-1]:
                role = "user" if msg["role"] == "user" else "model"
                content = msg["content"] if isinstance(msg["content"], str) else str(msg["content"])
                history.append({"role": role, "parts": [content]})

            chat = model.start_chat(history=history)
            last_msg = messages[-1]
            content = last_msg["content"] if isinstance(last_msg["content"], str) else str(last_msg["content"])

            response = chat.send_message(
                content,
                generation_config={"temperature": temperature, "max_output_tokens": max_tokens},
            )
            return self._parse_response(response.text)
        except Exception as exc:
            logger.error("google_error", error=str(exc))
            raise

    def chat_with_vision(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        return self.chat(messages, system_prompt, temperature, max_tokens)


# ── Factory ────────────────────────────────────────────────────


def get_llm_provider(
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> LLMProvider:
    """Create an LLM provider instance.

    Args:
        provider: "openai", "anthropic", or "google". Defaults to settings.
        model: Model name. Defaults to settings.
        api_key: API key override. Defaults to settings.
    """
    provider = provider or settings.default_ai_provider
    model = model or settings.default_ai_model

    if provider == "openai":
        return OpenAIProvider(api_key=api_key, model=model)
    elif provider == "anthropic":
        return AnthropicProvider(api_key=api_key, model=model)
    elif provider == "google":
        return GoogleProvider(api_key=api_key, model=model)
    else:
        raise ValueError(f"Unknown AI provider: {provider}. Use 'openai', 'anthropic', or 'google'.")
