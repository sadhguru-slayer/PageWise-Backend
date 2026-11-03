"""Shared Wiser AI runtime: multi-key Gemini clients, Sarvam AI fallback, compact prompts, async concurrency."""
import asyncio
import json
import os
import re
import time
from functools import lru_cache
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import types

_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_root_dir = os.path.dirname(_backend_dir)
load_dotenv(os.path.join(_backend_dir, ".env"))
load_dotenv(os.path.join(_root_dir, ".env"))
load_dotenv()

# Fast high-availability Gemini models to try in sequence
MODELS_TO_TRY = [
    "models/gemini-3.5-flash-lite",
    "models/gemini-3.8-flash",
    "models/gemini-3.5-flash",
    "models/gemini-3.1-flash-lite",
]

_primary_client: Optional[genai.Client] = None
_secondary_client: Optional[genai.Client] = None
_PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def get_gemini_client(key_type: str = "primary") -> Optional[genai.Client]:
    """Returns the Gemini genai.Client for either primary or secondary key."""
    global _primary_client, _secondary_client
    if key_type == "primary":
        if _primary_client is not None:
            return _primary_client
        api_key = (
            os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("NEXT_PUBLIC_GEMINI_API_KEY")
        )
        if not api_key:
            return None
        _primary_client = genai.Client(api_key=api_key.strip(), http_options={"timeout": 15000})
        return _primary_client
    elif key_type == "secondary":
        if _secondary_client is not None:
            return _secondary_client
        api_key_2 = (
            os.getenv("GEMINI_API_KEY_2")
            or os.getenv("GOOGLE_API_KEY_2")
        )
        if not api_key_2:
            return None
        _secondary_client = genai.Client(api_key=api_key_2.strip(), http_options={"timeout": 15000})
        return _secondary_client
    return None


@lru_cache(maxsize=8)
def load_prompt(filename: str) -> str:
    path = os.path.join(_PROMPT_DIR, filename)
    with open(path, "r", encoding="utf-8") as pf:
        return pf.read()


def clean_markdown_json(raw_text: str) -> str:
    text = (raw_text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def extract_plain_text(value: Any) -> str:
    """Extract human-readable plain text from TipTap JSON dict, JSON string, or HTML."""
    if value is None:
        return ""
    if isinstance(value, dict):
        if value.get("type") == "text":
            return value.get("text", "")
        texts = []
        for child in value.get("content", []):
            t = extract_plain_text(child)
            if t:
                texts.append(t)
        return " ".join(texts)
    if isinstance(value, list):
        return " ".join(extract_plain_text(item) for item in value)
    if isinstance(value, str):
        val_trim = value.strip()
        if (val_trim.startswith("{") and val_trim.endswith("}")) or (val_trim.startswith("[") and val_trim.endswith("]")):
            try:
                parsed = json.loads(val_trim)
                return extract_plain_text(parsed)
            except Exception:
                pass
        text = re.sub(r"<[^>]+>", " ", value)
        return re.sub(r"\s+", " ", text).strip()
    return str(value)


def strip_html(value: Any, max_chars: int = 2500) -> str:
    text = extract_plain_text(value)
    if len(text) > max_chars:
        return text[:max_chars] + "…"
    return text


def compact_header(header: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    header = header or {}
    keys = (
        "fullName",
        "name",
        "headline",
        "title",
        "email",
        "phone",
        "location",
        "website",
        "linkedin",
        "github",
        "contactLine",
    )
    return {k: header.get(k) for k in keys if header.get(k)}


def compact_sections(sections: Optional[List[Dict[str, Any]]], max_chars: int = 3500) -> List[Dict[str, Any]]:
    compact = []
    for sec in sections or []:
        raw = sec.get("content") or sec.get("contentHtml") or ""
        text = extract_plain_text(raw)
        if not text and sec.get("contentHtml"):
            text = extract_plain_text(sec.get("contentHtml"))
        compact.append({
            "id": sec.get("id"),
            "title": sec.get("title"),
            "contentHtml": text[:max_chars] if len(text) > max_chars else text,
        })
    return compact


def compact_resume(resume: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    resume = resume or {}
    header = resume.get("header_json") or resume.get("header") or {}
    sections = resume.get("sections_json") or resume.get("sections") or []
    return {
        "id": resume.get("id"),
        "name": resume.get("name"),
        "header_json": compact_header(header),
        "sections_json": compact_sections(sections),
    }


def compact_previous_resumes(resumes: Optional[List[Dict[str, Any]]], limit: int = 2) -> str:
    if not resumes:
        return "None provided."
    blocks = []
    for p in resumes[:limit]:
        name = p.get("name", "Previous Resume")
        snippets = []
        for s in (p.get("sections_json") or p.get("sections") or []):
            title = s.get("title", "")
            text = strip_html(s.get("contentHtml") or s.get("content") or "", max_chars=280)
            if text:
                snippets.append(f"[{title}]: {text}")
        if snippets:
            blocks.append(f"Resume '{name}':\n" + "\n".join(snippets))
    return "\n\n".join(blocks) if blocks else "None provided."


async def _execute_gemini_models(
    client: genai.Client,
    prompt: str,
    temperature: float = 0.2,
    timeout: float = 12.0,
    key_label: str = "GEMINI_API_KEY",
) -> Optional[str]:
    """Tries the configured Gemini model chain for a specific client."""
    for model_name in MODELS_TO_TRY:
        t0 = time.time()
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=temperature,
                    ),
                ),
                timeout=timeout
            )
            text = (response.text or "").strip()
            if text:
                elapsed = time.time() - t0
                print(f"[Wiser AI] Used {key_label} ({model_name}) in {elapsed:.2f}s")
                return text
        except asyncio.TimeoutError:
            elapsed = time.time() - t0
            print(f"[Wiser AI] {key_label} ({model_name}) timed out after {elapsed:.2f}s, trying next model...")
        except Exception as e:
            elapsed = time.time() - t0
            print(f"[Wiser AI] {key_label} ({model_name}) error ({elapsed:.2f}s): {e}")
    return None


async def _call_sarvam_chat(
    prompt: str,
    sarvam_key: str,
    temperature: float = 0.2,
    timeout: float = 45.0
) -> Optional[str]:
    """
    Sarvam AI Chat Completions fallback.
    Uses official V1 API authentication and JSON response mode.
    """

    url = "https://api.sarvam.ai/v1/chat/completions"

    api_key = sarvam_key.strip()
    if not api_key:
        print("Sarvam API key is missing")
        return None

    model = os.getenv("SARVAM_MODEL", "sarvam-105b")

    # V1 supported models
    allowed_models = {
        "sarvam-105b",
        "sarvam-105b-conversations",
    }

    if model not in allowed_models:
        print("Unsupported Sarvam V1 model: %s", model)
        return None

    headers = {
        "api-subscription-key": api_key,
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a specialized career document parser "
                    "and optimizer. Return ONLY a valid JSON object "
                    "matching the exact schema requested by the user. "
                    "Do not include markdown fences or explanations. "
                    "Never invent candidate qualifications, skills, "
                    "experience, metrics or achievements."
                )
            },
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": temperature,
        "max_tokens": int(os.getenv("SARVAM_MAX_TOKENS", "4096")),
        "response_format": {
            "type": "json_object"
        },
        "reasoning_effort": os.getenv(
            "SARVAM_REASONING_EFFORT", "low"
        ),
    }

    start_time = time.monotonic()

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:

            response = await client.post(
                url,
                headers=headers,
                json=payload,
            )

            if response.status_code != 200:
                print(
                    "Sarvam API returned HTTP %s: %s",
                    response.status_code,
                    response.text[:300],
                )
                return None

            data = response.json()

            choices = data.get("choices") or []
            if not choices:
                print("Sarvam returned no completion choices")
                return None

            message = choices[0].get("message") or {}
            content = message.get("content")

            if not isinstance(content, str) or not content.strip():
                print(
                    "Sarvam returned empty content. Finish reason: %s",
                    choices[0].get("finish_reason"),
                )
                return None

            elapsed = time.monotonic() - start_time

            print(
                "Sarvam fallback succeeded: model=%s, time=%.2fs",
                model,
                elapsed,
            )

            return content.strip()

    except httpx.TimeoutException:
        print("Sarvam request timed out after %ss", timeout)

    except httpx.HTTPError as exc:
        print("Sarvam HTTP request failed: %s", exc)

    except (ValueError, KeyError, IndexError) as exc:
        print("Invalid Sarvam response: %s", exc)

    except Exception:
        print("Unexpected Sarvam invocation failure")

    return None

async def async_generate_json(
    prompt: str,
    temperature: float = 0.2,
    timeout: float = 12.0
) -> Dict[str, Any]:
    """
    Multi-tier resilient LLM execution pipeline:
    Tier 1: Primary GEMINI_API_KEY across MODELS_TO_TRY.
    Tier 2: Secondary GEMINI_API_KEY_2 across MODELS_TO_TRY (if Tier 1 hits quota/rate limits/fails).
    Tier 3: SARVAM_API_KEY via Sarvam AI API (if Gemini fails or is rate-limited).
    """
    response_text = None

    # ── Tier 1: Primary Gemini Key ──────────────────────────────────────────
    primary_client = get_gemini_client("primary")
    if primary_client:
        response_text = await _execute_gemini_models(
            primary_client,
            prompt,
            temperature=temperature,
            timeout=timeout,
            key_label="GEMINI_API_KEY (Primary)",
        )

    # ── Tier 2: Secondary Gemini Key Fallback ───────────────────────────────
    if not response_text:
        secondary_client = get_gemini_client("secondary")
        if secondary_client:
            print("[Wiser AI Fallback] Primary Gemini unavailable or rate-limited. Activating Tier 2: GEMINI_API_KEY_2...")
            response_text = await _execute_gemini_models(
                secondary_client,
                prompt,
                temperature=temperature,
                timeout=timeout,
                key_label="GEMINI_API_KEY_2 (Secondary Backup)",
            )

    # ── Tier 3: Sarvam AI Fallback ──────────────────────────────────────────
    if not response_text:
        sarvam_key = os.getenv("SARVAM_API_KEY") or os.getenv("SARVAM_AI_API_KEY")
        if sarvam_key:
            print("[Wiser AI Fallback] Gemini key chains exhausted. Activating Tier 3: SARVAM_API_KEY backup...")
            response_text = await _call_sarvam_chat(
                prompt,
                sarvam_key=sarvam_key,
                temperature=temperature,
                timeout=timeout + 4.0,
            )

    if not response_text:
        raise RuntimeError(
            "Wiser AI request failed across all configured LLM providers (GEMINI_API_KEY, GEMINI_API_KEY_2, SARVAM_API_KEY). "
            "Please check API quotas or network availability."
        )

    cleaned = clean_markdown_json(response_text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as jde:
        # Attempt loose regex JSON object or array extraction if wrapped
        match = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass
        print(f"[Wiser AI] JSON parse error: {jde}\nResponse: {cleaned[:400]}")
        raise ValueError(f"AI returned invalid JSON: {jde}")


def generate_json(prompt: str, temperature: float = 0.2, timeout: float = 12.0) -> Dict[str, Any]:
    """Synchronous fallback wrapper that safely executes async_generate_json without deadlocks."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, async_generate_json(prompt, temperature, timeout)).result()
    else:
        return asyncio.run(async_generate_json(prompt, temperature, timeout))
