"""Shared Wiser AI runtime: one Gemini client, high-availability model fallback, compact prompts, async concurrency."""
import asyncio
import json
import os
import re
import time
from functools import lru_cache
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types

_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_root_dir = os.path.dirname(_backend_dir)
load_dotenv(os.path.join(_backend_dir, ".env"))
load_dotenv(os.path.join(_root_dir, ".env"))
load_dotenv()

# High-availability fast fallback chain:
# 1. models/gemini-3.5-flash-lite: sub-second latency, highest concurrency availability
# 2. models/gemini-3.5-flash: high capacity general flash model
# 3. models/gemini-3.8-flash: next-generation model
# 4. models/gemini-flash-latest: dynamic stable alias
MODELS_TO_TRY = [
    "models/gemini-3.5-flash-lite",
    "models/gemini-3.5-flash",
    "models/gemini-3.8-flash",
    "models/gemini-flash-latest",
]

_client: Optional[genai.Client] = None
_PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def get_gemini_client() -> genai.Client:
    global _client
    if _client is not None:
        return _client
    api_key = (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("NEXT_PUBLIC_GEMINI_API_KEY")
    )
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is not configured in the environment or .env file."
        )
    _client = genai.Client(api_key=api_key.strip(), http_options={"timeout": 15000})
    return _client


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


async def async_generate_json(
    prompt: str,
    temperature: float = 0.2,
    timeout: float = 12.0
) -> Dict[str, Any]:
    """
    Non-blocking async Gemini query with strict per-model timeout and immediate fallback.
    Prevents threadpool starvation and avoids blocking the main asyncio event loop.
    """
    client = get_gemini_client()
    last_error = None
    response_text = ""

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
                print(f"[Wiser AI] Used model {model_name} in {elapsed:.2f}s")
                response_text = text
                break
        except asyncio.TimeoutError:
            elapsed = time.time() - t0
            print(f"[Wiser AI] Model {model_name} timed out after {elapsed:.2f}s, trying fallback...")
            last_error = f"{model_name} timed out after {elapsed:.2f}s"
        except Exception as e:
            elapsed = time.time() - t0
            print(f"[Wiser AI] Model {model_name} failed ({elapsed:.2f}s): {e}, trying fallback...")
            last_error = e

    if not response_text:
        raise RuntimeError(f"Wiser AI request failed: {last_error}")

    response_text = clean_markdown_json(response_text)
    try:
        return json.loads(response_text)
    except json.JSONDecodeError as jde:
        print(f"[Wiser AI] JSON parse error: {jde}\nResponse: {response_text[:400]}")
        raise ValueError(f"AI returned invalid JSON: {jde}")


def generate_json(prompt: str, temperature: float = 0.2, timeout: float = 12.0) -> Dict[str, Any]:
    """
    Synchronous fallback wrapper that safely executes async_generate_json without deadlocks.
    """
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
