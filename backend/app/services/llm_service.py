"""
LLM Service
大语言模型服务 - 支持OpenAI和Anthropic
"""

import logging
import json
from typing import Optional, Dict, Any, List, AsyncGenerator
from functools import lru_cache

from ..core.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    """
    LLM服务
    支持:
    - OpenAI (GPT-4, GPT-3.5)
    - Anthropic (Claude)
    """

    def __init__(self, provider: Optional[str] = None):
        self.provider = provider or settings.DEFAULT_LLM_PROVIDER
        self._openai_client = None
        self._anthropic_client = None

        self._init_clients()

    def _init_clients(self):
        """Initialize LLM clients"""
        # OpenAI
        if settings.OPENAI_API_KEY:
            try:
                from openai import AsyncOpenAI

                self._openai_client = AsyncOpenAI(
                    api_key=settings.OPENAI_API_KEY,
                    base_url=settings.OPENAI_API_BASE,
                )
                logger.info("Initialized OpenAI client")
            except ImportError:
                logger.warning("openai package not installed")

        # Anthropic
        if settings.ANTHROPIC_API_KEY:
            try:
                from anthropic import AsyncAnthropic

                self._anthropic_client = AsyncAnthropic(
                    api_key=settings.ANTHROPIC_API_KEY,
                )
                logger.info("Initialized Anthropic client")
            except ImportError:
                logger.warning("anthropic package not installed")

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        provider: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        """
        Generate text completion
        
        Args:
            prompt: User prompt
            system_prompt: System prompt (optional)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            provider: Override default provider
            
        Returns:
            Generated text or None on error
        """
        provider = provider or self.provider

        try:
            if provider == "openai" and self._openai_client:
                return await self._generate_openai(
                    prompt, system_prompt, temperature, max_tokens, **kwargs
                )
            elif provider == "anthropic" and self._anthropic_client:
                return await self._generate_anthropic(
                    prompt, system_prompt, temperature, max_tokens, **kwargs
                )
            else:
                logger.error(f"No client available for provider: {provider}")
                return None
        except Exception as e:
            logger.error(f"LLM generation error ({provider}): {e}")
            return None

    async def _generate_openai(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        **kwargs,
    ) -> Optional[str]:
        """Generate using OpenAI"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await self._openai_client.chat.completions.create(
            model=kwargs.get("model", settings.OPENAI_MODEL),
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return response.choices[0].message.content

    async def _generate_anthropic(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        **kwargs,
    ) -> Optional[str]:
        """Generate using Anthropic"""
        response = await self._anthropic_client.messages.create(
            model=kwargs.get("model", settings.ANTHROPIC_MODEL),
            max_tokens=max_tokens,
            system=system_prompt or "You are a helpful assistant.",
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )

        return response.content[0].text

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        provider: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Generate text with streaming"""
        provider = provider or self.provider

        try:
            if provider == "openai" and self._openai_client:
                async for chunk in self._stream_openai(
                    prompt, system_prompt, temperature, max_tokens
                ):
                    yield chunk
            elif provider == "anthropic" and self._anthropic_client:
                async for chunk in self._stream_anthropic(
                    prompt, system_prompt, temperature, max_tokens
                ):
                    yield chunk
        except Exception as e:
            logger.error(f"LLM streaming error ({provider}): {e}")
            yield ""

    async def _stream_openai(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[str, None]:
        """Stream using OpenAI"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        stream = await self._openai_client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def _stream_anthropic(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[str, None]:
        """Stream using Anthropic"""
        async with self._anthropic_client.messages.stream(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system_prompt or "You are a helpful assistant.",
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        **kwargs,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate JSON response (with parsing)
        
        Uses lower temperature for more deterministic JSON output
        """
        # Add JSON instruction to system prompt
        json_system = (system_prompt or "") + (
            "\n\nIMPORTANT: Respond ONLY with valid JSON. "
            "Do not include any text before or after the JSON."
        )

        result = await self.generate(
            prompt=prompt,
            system_prompt=json_system,
            temperature=temperature,
            **kwargs,
        )

        if not result:
            return None

        try:
            # Try to extract JSON from response
            result = result.strip()

            # Handle markdown code blocks
            if result.startswith("```json"):
                result = result[7:]
            if result.startswith("```"):
                result = result[3:]
            if result.endswith("```"):
                result = result[:-3]

            return json.loads(result.strip())
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error: {e}\nResponse: {result[:500]}")
            return None


# Singleton instance
_llm_service: Optional[LLMService] = None


@lru_cache()
def get_llm_service(provider: Optional[str] = None) -> LLMService:
    """Get singleton LLM service instance"""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService(provider=provider)
    return _llm_service

