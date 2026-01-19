"""
Personal Model Service (OpenAI-compatible, e.g. vLLM)

This service is used by "小书童" features:
- Personalized chat / digital-twin companion
- Personalized learning suggestions / review coaching (Tony first)

Design notes:
- We intentionally do NOT reuse `LLMService` here, because `LLMService` is meant for upstream
  providers (OpenAI/Anthropic). The personal model is a local OpenAI-compatible endpoint.
- Default endpoint matches the course vLLM start command:
    http://127.0.0.1:8001/v1
  and model name defaults to "tony-dpo" (LoRA adapter exposed by vLLM).
"""

from __future__ import annotations

import logging
import os
import json
from pathlib import Path
import random
import time
from functools import lru_cache
from typing import Any, AsyncIterator, Dict, List, Optional

from ..base_config import get_base_settings

logger = logging.getLogger(__name__)

def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _truncate(s: str, n: int = 240) -> str:
    s = (s or "").replace("\n", " ").strip()
    if len(s) <= n:
        return s
    return s[:n] + "...(truncated)"

def _trace_enabled() -> bool:
    # Default ON (as requested). Can be disabled to avoid privacy/log explosion:
    #   export PERSONAL_MODEL_TRACE_ENABLED=false
    v = os.environ.get("PERSONAL_MODEL_TRACE_ENABLED")
    if v is None:
        return True
    return _truthy(v)


def _trace_sample_rate() -> float:
    try:
        return float(os.environ.get("PERSONAL_MODEL_TRACE_SAMPLE_RATE") or "1.0")
    except Exception:
        return 1.0


def _trace_path(module: str) -> Path:
    # Default: ./logs/trace_personal_model_<module>.jsonl
    # Override:
    #   export PERSONAL_MODEL_TRACE_PATH=./logs/trace_personal_model.jsonl
    p = (os.environ.get("PERSONAL_MODEL_TRACE_PATH") or "").strip()
    if p:
        return Path(p)
    d = (os.environ.get("PERSONAL_MODEL_TRACE_DIR") or "./logs").strip() or "./logs"
    return Path(d) / f"trace_personal_model_{module}.jsonl"


def _looks_like_missing_chat_template_error(e: Exception) -> bool:
    s = str(e) or ""
    s = s.lower()
    return ("chat template" in s and "must provide" in s) or ("default chat template" in s and "no longer allowed" in s)


def _messages_to_prompt(messages: List[Dict[str, str]]) -> str:
    """
    Convert chat messages into a single prompt string for `/v1/completions`.
    This is a robust fallback for vLLM when `/v1/chat/completions` fails due to missing chat_template.
    """
    parts: List[str] = []
    for m in (messages or []):
        role = str(m.get("role") or "user").strip().lower()
        content = str(m.get("content") or "").rstrip()
        if not content:
            continue
        if role == "system":
            parts.append(f"System:\n{content}")
        elif role == "assistant":
            parts.append(f"Assistant:\n{content}")
        else:
            parts.append(f"User:\n{content}")
    prompt = "\n\n".join(parts).strip()
    if prompt:
        prompt += "\n\nAssistant:\n"
    return prompt


def _write_trace_line(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


class PersonalModelService:
    def __init__(self, module: str):
        self._module = str(module or "").strip().lower()
        self._client = None
        # If vLLM is started without `--chat-template` (transformers>=4.44),
        # `/v1/chat/completions` will 400. We detect once and then route future
        # calls to `/v1/completions` to avoid noisy repeated 400s.
        self._force_completions = False
        self._force_completions_logged = False
        self._models_cache: Optional[List[Dict[str, Any]]] = None
        self._models_cache_ts: float = 0.0

    def _models_cache_ttl_seconds(self) -> float:
        try:
            return float(os.environ.get("PERSONAL_MODEL_MODELS_CACHE_TTL_SECONDS") or "30")
        except Exception:
            return 30.0

    async def list_models_cached(self) -> List[Dict[str, Any]]:
        """
        Cached /v1/models to avoid per-request network calls.
        """
        ttl = max(0.0, self._models_cache_ttl_seconds())
        now = time.monotonic()
        if self._models_cache is not None and (now - float(self._models_cache_ts)) <= ttl:
            return self._models_cache
        models = await self.list_models()
        self._models_cache = models
        self._models_cache_ts = now
        return models

    async def resolve_model_for_subject(
        self,
        *,
        subject: Optional[str],
        strict: bool = False,
    ) -> Dict[str, Any]:
        """
        Resolve which served model id to use for a given subject.

        Convention:
        - subject-specific LoRA:  <module>-sft-<subject>
        - fallback:              settings PERSONAL_MODEL_MODEL_<MODULE>

        Return:
          { "model": str, "subject_model": Optional[str], "used_subject_model": bool, "warning": Optional[str] }
        """
        subj = (subject or "").strip().lower()
        if not subj:
            return {"model": self.default_model, "subject_model": None, "used_subject_model": False, "warning": None}

        # Optional explicit override: PERSONAL_MODEL_MODEL_<MODULE>_<SUBJECT>=...
        override_key = f"PERSONAL_MODEL_MODEL_{self._module.upper()}_{subj.upper()}"
        override = (os.environ.get(override_key) or "").strip()
        subject_model = override or f"{self._module}-sft-{subj}"

        try:
            models = await self.list_models_cached()
            ids = {str(m.get("id") or "").strip() for m in (models or []) if isinstance(m, dict)}
            if subject_model in ids:
                return {"model": subject_model, "subject_model": subject_model, "used_subject_model": True, "warning": None}
        except Exception:
            # If listing models fails, do not block the main call path; use default.
            return {"model": self.default_model, "subject_model": subject_model, "used_subject_model": False, "warning": None}

        if strict:
            raise RuntimeError(
                f"Subject model not available: expected '{subject_model}'. "
                f"Run train-sft for subject={subj}, then restart vLLM so it loads the LoRA."
            )

        return {
            "model": self.default_model,
            "subject_model": subject_model,
            "used_subject_model": False,
            "warning": f"Subject-specific LoRA not found: {subject_model}. Falling back to default model: {self.default_model}",
        }

    def _get_client(self):
        if self._client is not None:
            return self._client

        settings = get_base_settings()
        try:
            from openai import AsyncOpenAI
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "openai package is required for PersonalModelService.\n"
                "Install dependencies: pip install -r requirements.txt\n"
                f"original_error={repr(e)}"
            ) from e

        base_url = settings.personal_model_api_base_for(self._module)
        api_key = settings.personal_model_api_key_for(self._module)
        timeout = settings.personal_model_timeout_for(self._module)

        # Classroom default: personal model is on localhost. Many student environments export
        # ALL_PROXY/HTTP(S)_PROXY, which can break localhost calls (goes through SOCKS/HTTP proxy).
        # By default, we **do not** trust env proxies for the personal model client.
        trust_env = _truthy(os.environ.get("PERSONAL_MODEL_HTTP_TRUST_ENV"))
        try:
            import httpx

            http_client = httpx.AsyncClient(timeout=timeout, trust_env=trust_env)
        except Exception:
            http_client = None

        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            http_client=http_client,
        )
        return self._client

    @property
    def enabled(self) -> bool:
        settings = get_base_settings()
        return settings.personal_model_enabled_for(self._module)

    @property
    def default_model(self) -> str:
        settings = get_base_settings()
        return settings.personal_model_model_for(self._module)

    async def list_models(self) -> List[Dict[str, Any]]:
        """
        Return models from /v1/models.
        Useful for health checks and debugging LoRA availability.
        """
        client = self._get_client()
        t0 = time.monotonic()
        res = await client.models.list()
        dt_ms = int((time.monotonic() - t0) * 1000)
        # openai>=1.x returns a pydantic-like object; convert to plain dicts
        out: List[Dict[str, Any]] = []
        for m in (res.data or []):
            try:
                out.append(m.model_dump())
            except Exception:
                out.append({"id": getattr(m, "id", None)})
        logger.info(
            "[personal_model] list_models ok module=%s count=%s dt_ms=%s",
            self._module,
            len(out),
            dt_ms,
        )
        return out

    async def chat(
        self,
        *,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 800,
        trace_id: Optional[str] = None,
        trace: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> str:
        """
        Call OpenAI-compatible chat completion endpoint.
        """
        client = self._get_client()
        model_name = model or self.default_model
        verbose = _truthy(os.environ.get("PERSONAL_MODEL_LOG_VERBOSE"))
        do_trace = _trace_enabled()
        if do_trace and _trace_sample_rate() < 1.0:
            do_trace = (random.random() < max(0.0, min(1.0, _trace_sample_rate())))

        t0 = time.monotonic()
        if do_trace:
            try:
                _write_trace_line(
                    _trace_path(self._module),
                    {
                        "event": "personal_model.request",
                        "ts": time.time(),
                        "module": self._module,
                        "trace_id": trace_id,
                        "model": model_name,
                        "temperature": float(temperature),
                        "max_tokens": int(max_tokens),
                        "messages": messages,  # full prompt/history
                        "retrieval": (trace or {}).get("retrieval"),
                        "meta": {k: v for k, v in (trace or {}).items() if k != "retrieval"},
                    },
                )
            except Exception as e:
                logger.debug("[personal_model] trace write failed (request): %s", repr(e))

        async def _call_completions(*, reason: str, original_error: Optional[Exception] = None) -> str:
            prompt = _messages_to_prompt(messages)
            t1 = time.monotonic()
            resp2 = await client.completions.create(
                model=model_name,
                prompt=prompt,
                temperature=float(temperature),
                max_tokens=int(max_tokens),
            )
            txt = getattr(resp2.choices[0], "text", "") if resp2 and resp2.choices else ""
            content2 = (txt or "").strip()
            dt_ms2 = int((time.monotonic() - t1) * 1000)
            logger.warning(
                "[personal_model] using /v1/completions module=%s model=%s dt_ms=%s reason=%s",
                self._module,
                model_name,
                dt_ms2,
                reason,
            )
            if do_trace:
                try:
                    _write_trace_line(
                        _trace_path(self._module),
                        {
                            "event": "personal_model.completions",
                            "ts": time.time(),
                            "module": self._module,
                            "trace_id": trace_id,
                            "model": model_name,
                            "dt_ms": dt_ms2,
                            "reason": reason,
                            "prompt": prompt,
                            "output": content2,
                            "error": repr(original_error) if original_error is not None else None,
                        },
                    )
                except Exception:
                    pass
            return content2

        try:
            # Optional override: force completions (avoid any chat_template issues).
            if self._force_completions or _truthy(os.environ.get("PERSONAL_MODEL_FORCE_COMPLETIONS")):
                if self._force_completions and not self._force_completions_logged:
                    logger.warning(
                        "[personal_model] forcing /v1/completions for module=%s (chat_template missing was detected previously)",
                        self._module,
                    )
                    self._force_completions_logged = True
                return await _call_completions(reason="force_completions")

            resp = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=float(temperature),
                max_tokens=int(max_tokens),
                **kwargs,
            )
        except Exception as e:
            # vLLM + transformers>=4.44: tokenizer without chat_template will hard-fail chat-completions.
            # Prefer fixing by injecting `--chat-template` at vLLM startup; but keep a runtime fallback
            # to avoid breaking the classroom demo.
            if _looks_like_missing_chat_template_error(e):
                # Remember to avoid repeated noisy 400s on subsequent calls.
                self._force_completions = True
                try:
                    return await _call_completions(reason="chat_template_missing", original_error=e)
                except Exception:
                    # If fallback also fails, proceed to normal error handling below.
                    pass

            dt_ms = int((time.monotonic() - t0) * 1000)
            logger.exception(
                "[personal_model] chat failed module=%s model=%s dt_ms=%s err=%s",
                self._module,
                model_name,
                dt_ms,
                repr(e),
            )
            if do_trace:
                try:
                    _write_trace_line(
                        _trace_path(self._module),
                        {
                            "event": "personal_model.error",
                            "ts": time.time(),
                            "module": self._module,
                            "trace_id": trace_id,
                            "model": model_name,
                            "dt_ms": dt_ms,
                            "error": repr(e),
                        },
                    )
                except Exception:
                    pass
            raise

        content = (resp.choices[0].message.content or "").strip()
        dt_ms = int((time.monotonic() - t0) * 1000)
        if do_trace:
            try:
                _write_trace_line(
                    _trace_path(self._module),
                    {
                        "event": "personal_model.response",
                        "ts": time.time(),
                        "module": self._module,
                        "trace_id": trace_id,
                        "model": model_name,
                        "dt_ms": dt_ms,
                        "output": content,  # full output
                        "usage": getattr(resp, "usage", None).model_dump() if getattr(resp, "usage", None) else None,
                    },
                )
            except Exception as e:
                logger.debug("[personal_model] trace write failed (response): %s", repr(e))

        if verbose:
            preview = _truncate(content, 400)
            logger.info(
                "[personal_model] chat ok module=%s model=%s msgs=%s dt_ms=%s out_len=%s out_preview=%r",
                self._module,
                model_name,
                len(messages or []),
                dt_ms,
                len(content),
                preview,
            )
        else:
            logger.info(
                "[personal_model] chat ok module=%s model=%s msgs=%s dt_ms=%s out_len=%s",
                self._module,
                model_name,
                len(messages or []),
                dt_ms,
                len(content),
            )
        return content

    async def chat_stream(
        self,
        *,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 800,
        trace_id: Optional[str] = None,
        trace: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """
        Stream tokens from the personal model.

        Transport: OpenAI-compatible streaming (SSE-like chunks from OpenAI client).
        Output: yields plain text deltas.
        """
        client = self._get_client()
        model_name = model or self.default_model
        do_trace = _trace_enabled()
        if do_trace and _trace_sample_rate() < 1.0:
            do_trace = (random.random() < max(0.0, min(1.0, _trace_sample_rate())))

        t0 = time.monotonic()
        if do_trace:
            try:
                _write_trace_line(
                    _trace_path(self._module),
                    {
                        "event": "personal_model.request",
                        "ts": time.time(),
                        "module": self._module,
                        "trace_id": trace_id,
                        "model": model_name,
                        "temperature": float(temperature),
                        "max_tokens": int(max_tokens),
                        "stream": True,
                        "messages": messages,
                        "retrieval": (trace or {}).get("retrieval"),
                        "meta": {k: v for k, v in (trace or {}).items() if k != "retrieval"},
                    },
                )
            except Exception:
                pass

        async def _stream_completions(*, reason: str, original_error: Optional[Exception] = None) -> AsyncIterator[str]:
            prompt = _messages_to_prompt(messages)
            out_parts: List[str] = []
            try:
                stream = await client.completions.create(
                    model=model_name,
                    prompt=prompt,
                    temperature=float(temperature),
                    max_tokens=int(max_tokens),
                    stream=True,
                )
                async for ev in stream:
                    delta = ""
                    try:
                        delta = getattr(ev.choices[0], "text", "") or ""
                    except Exception:
                        delta = ""
                    if delta:
                        out_parts.append(delta)
                        yield delta
            finally:
                dt_ms = int((time.monotonic() - t0) * 1000)
                final_text = ("".join(out_parts) or "").strip()
                logger.warning(
                    "[personal_model] stream via /v1/completions module=%s model=%s dt_ms=%s reason=%s out_len=%s",
                    self._module,
                    model_name,
                    dt_ms,
                    reason,
                    len(final_text),
                )
                if do_trace:
                    try:
                        _write_trace_line(
                            _trace_path(self._module),
                            {
                                "event": "personal_model.response",
                                "ts": time.time(),
                                "module": self._module,
                                "trace_id": trace_id,
                                "model": model_name,
                                "dt_ms": dt_ms,
                                "stream": True,
                                "reason": reason,
                                "prompt": prompt,
                                "output": final_text,
                                "error": repr(original_error) if original_error is not None else None,
                            },
                        )
                    except Exception:
                        pass

        # Optional override: force completions (avoid chat_template issues entirely).
        if self._force_completions or _truthy(os.environ.get("PERSONAL_MODEL_FORCE_COMPLETIONS")):
            if self._force_completions and not self._force_completions_logged:
                logger.warning(
                    "[personal_model] forcing stream via /v1/completions for module=%s (chat_template missing was detected previously)",
                    self._module,
                )
                self._force_completions_logged = True
            async for d in _stream_completions(reason="force_completions"):
                yield d
            return

        out_parts: List[str] = []
        try:
            stream = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=float(temperature),
                max_tokens=int(max_tokens),
                stream=True,
                **kwargs,
            )
            async for ev in stream:
                delta = ""
                try:
                    delta = getattr(ev.choices[0].delta, "content", "") or ""
                except Exception:
                    delta = ""
                if delta:
                    out_parts.append(delta)
                    yield delta
        except Exception as e:
            if _looks_like_missing_chat_template_error(e):
                self._force_completions = True
                async for d in _stream_completions(reason="chat_template_missing", original_error=e):
                    yield d
                return

            dt_ms = int((time.monotonic() - t0) * 1000)
            logger.exception(
                "[personal_model] chat_stream failed module=%s model=%s dt_ms=%s err=%s",
                self._module,
                model_name,
                dt_ms,
                repr(e),
            )
            if do_trace:
                try:
                    _write_trace_line(
                        _trace_path(self._module),
                        {
                            "event": "personal_model.error",
                            "ts": time.time(),
                            "module": self._module,
                            "trace_id": trace_id,
                            "model": model_name,
                            "dt_ms": dt_ms,
                            "stream": True,
                            "error": repr(e),
                        },
                    )
                except Exception:
                    pass
            raise

        dt_ms = int((time.monotonic() - t0) * 1000)
        final_text = ("".join(out_parts) or "").strip()
        if do_trace:
            try:
                _write_trace_line(
                    _trace_path(self._module),
                    {
                        "event": "personal_model.response",
                        "ts": time.time(),
                        "module": self._module,
                        "trace_id": trace_id,
                        "model": model_name,
                        "dt_ms": dt_ms,
                        "stream": True,
                        "output": final_text,
                    },
                )
            except Exception:
                pass


@lru_cache()
def get_personal_model_service(module: str) -> PersonalModelService:
    return PersonalModelService(module=module)

