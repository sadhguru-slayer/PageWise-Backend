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

import logging

logger = logging.getLogger(__name__)


_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_root_dir = os.path.dirname(_backend_dir)
load_dotenv(os.path.join(_backend_dir, ".env"))
load_dotenv(os.path.join(_root_dir, ".env"))
load_dotenv()

# Model routing table and fallback
MODEL_ROUTING = {
    "ats_check": "models/gemini-3.8-flash",
    "jd_edit": "models/gemini-3.8-flash",
    "resume_improvement": "models/gemini-3.8-flash",
    "small_edit": "models/gemini-3.1-flash-lite",
    "pdf_correction": "models/gemini-3.5-flash-lite",
}

FALLBACK_MODEL = "sarvam-105b"

# Active test configuration: Sarvam AI is primary for testing; other LLMs disabled for now
USE_SARVAM_PRIMARY = True

PARSE_MODELS = [MODEL_ROUTING["pdf_correction"]]
JD_REASONING_MODELS = [MODEL_ROUTING["jd_edit"]]
MODELS_TO_TRY = PARSE_MODELS

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


def compact_sections(sections: Optional[List[Dict[str, Any]]], max_chars: int = 4500) -> List[Dict[str, Any]]:
    compact = []
    for sec in sections or []:
        items = sec.get("items") or []
        compact_items = []
        html_parts = []

        if isinstance(items, list) and items:
            for it in items:
                if not isinstance(it, dict):
                    continue
                item_id = it.get("id") or ""
                title = it.get("title") or it.get("project_title") or it.get("institution") or ""
                company = it.get("company") or it.get("role") or ""
                summary = it.get("summary") or ""
                pts = it.get("points") or []

                indexed_points = []
                if isinstance(pts, list):
                    for b_idx, p in enumerate(pts):
                        if isinstance(p, str) and p.strip():
                            indexed_points.append({
                                "point_index": b_idx,
                                "text": p.strip()
                            })

                compact_items.append({
                    "item_id": item_id,
                    "title": title,
                    "company": company,
                    "summary": summary,
                    "points": indexed_points,
                })

                header_line = f"<strong>{title}</strong>"
                if company:
                    header_line += f" | {company}"
                if header_line != "<strong></strong>":
                    html_parts.append(f"<p>{header_line}</p>")
                if summary:
                    html_parts.append(f"<p>{summary}</p>")
                if indexed_points:
                    lis = "".join(f"<li data-item-id=\"{item_id}\" data-point-index=\"{pt['point_index']}\">{pt['text']}</li>" for pt in indexed_points)
                    html_parts.append(f"<ul>{lis}</ul>")

        content_html = "".join(html_parts)
        if not content_html:
            content_html = sec.get("contentHtml") or sec.get("content") or ""
            if not isinstance(content_html, str):
                content_html = extract_plain_text(content_html)

        compact.append({
            "id": sec.get("id"),
            "title": sec.get("title"),
            "items": compact_items,
            "contentHtml": content_html[:max_chars] if len(content_html) > max_chars else content_html,
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
    prompt: Any,
    temperature: float = 0.2,
    timeout: float = 12.0,
    key_label: str = "GEMINI_API_KEY",
    model_list: Optional[List[str]] = None,
    thinking_budget: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Tries the configured Gemini model chain for a specific client.
    Returns dict {"text": str, "usage": dict, "model": str} or None.
    """
    models = model_list or PARSE_MODELS
    for model_name in models:
        t0 = time.time()
        try:
            config_kwargs = {
                "response_mime_type": "application/json",
                "temperature": temperature,
            }
            if thinking_budget is not None and thinking_budget > 0:
                config_kwargs["thinking_config"] = types.ThinkingConfig(
                    thinking_budget=thinking_budget
                )

            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(**config_kwargs),
                ),
                timeout=timeout
            )
            text = (response.text or "").strip()
            if text:
                elapsed = time.time() - t0
                usage_meta = getattr(response, "usage_metadata", None)
                usage_dict = {
                    "input_tokens": getattr(usage_meta, "prompt_token_count", 0) or 0,
                    "output_tokens": getattr(usage_meta, "candidates_token_count", 0) or 0,
                    "total_tokens": getattr(usage_meta, "total_token_count", 0) or 0,
                    "thoughts_tokens": getattr(usage_meta, "thoughts_token_count", 0) or 0,
                    "source": "gemini",
                }
                print(
                    f"[Wiser AI] Used {key_label} ({model_name}) in {elapsed:.2f}s | "
                    f"tokens: in={usage_dict['input_tokens']} out={usage_dict['output_tokens']} total={usage_dict['total_tokens']}"
                )
                return {
                    "text": text,
                    "usage": usage_dict,
                    "model": model_name,
                }
        except asyncio.TimeoutError:
            elapsed = time.time() - t0
            print(f"[Wiser AI] {key_label} ({model_name}) timed out after {elapsed:.2f}s, trying next model...")
        except Exception as e:
            elapsed = time.time() - t0
            print(f"[Wiser AI] {key_label} ({model_name}) error ({elapsed:.2f}s): {e}")
    return None


# async def _call_sarvam_chat(
#     prompt: str,
#     sarvam_key: str,
#     temperature: float = 0.2,
#     timeout: float = 45.0
# ) -> Optional[str]:
#     """
#     Sarvam AI Chat Completions fallback.
#     Uses official V1 API authentication and JSON response mode.
#     """

#     url = "https://api.sarvam.ai/v1/chat/completions"

#     api_key = sarvam_key.strip()
#     if not api_key:
#         print("Sarvam API key is missing")
#         return None

#     model = os.getenv("SARVAM_MODEL", "sarvam-105b")

#     # V1 supported models
#     allowed_models = {
#         "sarvam-105b",
#         "sarvam-105b-conversations",
#     }

#     if model not in allowed_models:
#         logger.warning("Unsupported Sarvam V1 model: %s", model)
#         return None

#     headers = {
#         "api-subscription-key": api_key,
#         "Content-Type": "application/json",
#     }

#     payload = {
#         "model": model,
#         "messages": [
#             {
#                 "role": "system",
#                 "content": (
#                     "You are a specialized career document parser "
#                     "and optimizer. Return ONLY a valid JSON object "
#                     "matching the exact schema requested by the user. "
#                     "Do not include markdown fences or explanations. "
#                     "Never invent candidate qualifications, skills, "
#                     "experience, metrics or achievements."
#                 )
#             },
#             {
#                 "role": "user",
#                 "content": prompt,
#             }
#         ],
#         "temperature": temperature,
#         "max_tokens": int(os.getenv("SARVAM_MAX_TOKENS", "4096")),
#         "response_format": {
#             "type": "json_object"
#         },
#         "reasoning_effort": os.getenv(
#             "SARVAM_REASONING_EFFORT", "low"
#         ),
#     }

#     start_time = time.monotonic()

#     try:
#         async with httpx.AsyncClient(timeout=timeout) as client:

#             response = await client.post(
#                 url,
#                 headers=headers,
#                 json=payload,
#             )

#             if response.status_code != 200:
#                 logger.error(
#                     "Sarvam API returned HTTP %s: %s",
#                     response.status_code,
#                     response.text[:300],
#                 )
#                 return None

#             data = response.json()

#             choices = data.get("choices") or []
#             if not choices:
#                 print("Sarvam returned no completion choices")
#                 return None

#             message = choices[0].get("message") or {}
#             content = message.get("content")

#             if not isinstance(content, str) or not content.strip():
#                 logger.warning(
#                     "Sarvam returned empty content. Finish reason: %s",
#                     choices[0].get("finish_reason"),
#                 )
#                 return None

#             elapsed = time.monotonic() - start_time

#             logger.info(
#                 "Sarvam fallback succeeded: model=%s, time=%.2fs",
#                 model,
#                 elapsed,
#             )

#             return content.strip()

#     except httpx.TimeoutException:
#         logger.error("Sarvam request timed out after %ss", timeout)

#     except httpx.HTTPError as exc:
#         logger.error("Sarvam HTTP request failed: %s", exc)

#     except (ValueError, KeyError, IndexError) as exc:
#         print("Invalid Sarvam response: %s", exc)

#     except Exception:
#         print("Unexpected Sarvam invocation failure")

#     return None




import os
import time
import asyncio
import logging

from typing import Optional
try:
    from sarvamai import AsyncSarvamAI
    from sarvamai.core.api_error import ApiError
except ImportError:
    AsyncSarvamAI = None
    ApiError = Exception

logger = logging.getLogger(__name__)

_sarvam_client: Optional[Any] = None
_sarvam_client_api_key: Optional[str] = None


def _get_sarvam_client(sarvam_key: str):
    """
    Reuse the asynchronous SarvamAI SDK client.
    Recreate it if the API key changes.
    """
    global _sarvam_client, _sarvam_client_api_key

    api_key = sarvam_key.strip()
    if not api_key:
        raise ValueError("Sarvam API key is missing")

    if AsyncSarvamAI is None:
        raise ImportError("sarvamai package is not installed.")

    if _sarvam_client is None or _sarvam_client_api_key != api_key:
        _sarvam_client = AsyncSarvamAI(
            api_subscription_key=api_key,
            timeout=120.0,
        )
        _sarvam_client_api_key = api_key

    return _sarvam_client


async def _execute_sarvam_completion(
    prompt: Any,
    temperature: float = 0.1,
    timeout: float = 90.0
) -> Optional[Dict[str, Any]]:
    """
    Executes chat completion using the official SarvamAI Python SDK (sarvamai).
    """
    sarvam_key = (os.getenv("SARVAM_API_KEY") or os.getenv("SARVAM_AI_API_KEY") or "").strip()
    if not sarvam_key:
        print("[Sarvam AI] No SARVAM_API_KEY found in environment.")
        return None

    # Flatten prompt to string if needed
    if isinstance(prompt, list):
        prompt_str = "\n\n".join(
            (p.get("content") or str(p)) if isinstance(p, dict) else str(p) for p in prompt
        )
    else:
        prompt_str = str(prompt)

    model_name = os.getenv("SARVAM_MODEL", FALLBACK_MODEL)
    max_tokens_val = int(os.getenv("SARVAM_MAX_TOKENS", "8192"))

    t0 = time.time()
    try:
        client = _get_sarvam_client(sarvam_key)
        response = await asyncio.wait_for(
            client.chat.completions(
                model=model_name,
                messages=[{"role": "user", "content": prompt_str}],
                temperature=temperature,
                max_tokens=max_tokens_val,
                response_format={"type": "json_object"},
                request_options={
                    "timeout_in_seconds": int(timeout),
                },
            ),
            timeout=timeout + 5.0,
        )

        choices = getattr(response, "choices", None) or []
        if not choices:
            print("[Sarvam AI] No completion choices returned by SarvamAI SDK.")
            return None

        choice = choices[0]
        message = getattr(choice, "message", None)
        text = getattr(message, "content", "") or ""

        usage_obj = getattr(response, "usage", None)
        in_tok = getattr(usage_obj, "prompt_tokens", 0) if usage_obj else 0
        out_tok = getattr(usage_obj, "completion_tokens", 0) if usage_obj else 0
        tot_tok = getattr(usage_obj, "total_tokens", 0) if usage_obj else 0

        elapsed = time.time() - t0
        usage = {
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_tokens": tot_tok,
            "source": "sarvam",
        }
        print(f"[Sarvam AI SDK] Succeeded with {model_name} in {elapsed:.2f}s | in={in_tok} out={out_tok}")
        return {
            "text": text.strip(),
            "usage": usage,
            "model": model_name,
        }

    except (asyncio.TimeoutError, TimeoutError):
        print(f"[Sarvam AI SDK] Timeout reached after {timeout:.0f}s")
        return None
    except ApiError as exc:
        print(f"[Sarvam AI SDK] API error status={getattr(exc, 'status_code', 'unknown')}: {getattr(exc, 'body', str(exc))}")
        return None
    except Exception as e:
        print(f"[Sarvam AI SDK] Execution failed: {e}")
        return None


async def async_generate_json(
    prompt: Any,
    temperature: float = 0.2,
    timeout: float = 12.0,
    task: str = "parse",
) -> Dict[str, Any]:
    """
    Multi-tier resilient LLM execution pipeline with true token usage tracking.
    When USE_SARVAM_PRIMARY is True, Sarvam AI (sarvam-105b) is invoked first.
    """
    exec_result: Optional[Dict[str, Any]] = None

    # ── Tier 1: Primary invocation ──────────────────────────────────────────
    if USE_SARVAM_PRIMARY:
        print(f"[Wiser AI] Invoking Sarvam AI ({FALLBACK_MODEL}) as primary provider...")
        exec_result = await _execute_sarvam_completion(prompt, temperature=0.0, timeout=90.0)
        if not exec_result or not (exec_result.get("text") or "").strip():
            print(f"[Wiser AI Fallback] Sarvam AI returned empty response. Activating Gemini fallback ({MODEL_ROUTING.get(task, 'models/gemini-3.8-flash')})...")
            exec_result = None

    # ── Tier 2: Gemini (Active when USE_SARVAM_PRIMARY is False or as fallback) ─
    if not exec_result:
        if task == "jd":
            models_to_use = JD_REASONING_MODELS
            thinking_budget = 1024
            eff_timeout = max(timeout, 30.0)
        else:
            models_to_use = PARSE_MODELS
            thinking_budget = None
            eff_timeout = timeout

        primary_client = get_gemini_client("primary")
        if primary_client:
            exec_result = await _execute_gemini_models(
                primary_client,
                prompt,
                temperature=temperature,
                timeout=eff_timeout,
                key_label="GEMINI_API_KEY (Primary)",
                model_list=models_to_use,
                thinking_budget=thinking_budget,
            )

        if not exec_result:
            secondary_client = get_gemini_client("secondary")
            if secondary_client:
                print("[Wiser AI Fallback] Primary Gemini unavailable. Activating Tier 2: GEMINI_API_KEY_2...")
                exec_result = await _execute_gemini_models(
                    secondary_client,
                    prompt,
                    temperature=temperature,
                    timeout=eff_timeout,
                    key_label="GEMINI_API_KEY_2 (Secondary Backup)",
                    model_list=models_to_use,
                    thinking_budget=thinking_budget,
                )

    if not exec_result:
        raise RuntimeError(
            "Wiser AI request failed: Sarvam AI is primary and failed or returned invalid response."
        )

    response_text = exec_result["text"]
    usage = exec_result.get("usage", {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "source": "unavailable",
    })
    model_name = exec_result.get("model", "Wiser AI")

    cleaned = clean_markdown_json(response_text)
    parsed: Optional[Dict[str, Any]] = None

    if cleaned:
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as jde:
            match = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(1))
                except Exception:
                    parsed = None

    if not parsed or not isinstance(parsed, dict):
        preview = (cleaned[:400] if cleaned else "EMPTY_RESPONSE")
        print(f"[Wiser AI] JSON parse error on response from {model_name}:\n{preview}")
        raise ValueError(
            f"AI provider ({model_name}) returned empty or truncated JSON. "
            "Please try again or switch model."
        )

    if isinstance(parsed, dict):
        parsed["_usage"] = {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "thoughts_tokens": usage.get("thoughts_tokens", 0),
            "model": model_name,
            "source": usage.get("source", "gemini"),
        }
        parsed["_ai_model"] = model_name

    return parsed


def generate_json(
    prompt: Any,
    temperature: float = 0.2,
    timeout: float = 12.0,
    task: str = "parse",
) -> Dict[str, Any]:
    """Synchronous fallback wrapper that safely executes async_generate_json without deadlocks."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, async_generate_json(prompt, temperature, timeout, task)).result()
    else:
        return asyncio.run(async_generate_json(prompt, temperature, timeout, task))
