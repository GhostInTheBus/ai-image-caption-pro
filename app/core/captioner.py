"""
Vision model integration for photo captioning.

Supports multiple backends:
  - Ollama  (local, default)           — no API key needed
  - Gemini  (Google)                   — aistudio.google.com
  - Claude  (Anthropic)                — console.anthropic.com
  - OpenAI  (ChatGPT/GPT-4o)          — platform.openai.com
"""
from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple

import ollama

# ── Prompt ────────────────────────────────────────────────────────────────────

CAPTION_PROMPT = """You are a professional photo archivist building a long-term searchable image archive. Study this photograph carefully — foreground AND background — then respond ONLY with a valid JSON object. No markdown, no code fences, just raw JSON.

{
  "caption": "...",
  "keywords": ["...", "..."]
}

CAPTION RULES
Write 2–4 natural, readable sentences as a knowledgeable observer would describe the image to someone who hasn't seen it. Cover what is in the foreground, what is visible in the background, the quality of light, and any detail that gives the image character. Name specific things you can identify with confidence. Do NOT start with "A photo of", "An image of", or "This image shows". Do NOT infer purpose, occasion, or relationships — no "vacation", "family outing", "tourist", "celebration", "wedding" — unless a sign or banner in the frame explicitly says so. Describe people by what they are doing and wearing, not who they might be or why they are there.

KEYWORD RULES — 3 to 7 keywords only
Keywords must be specific and high-signal. Ask yourself: would this keyword meaningfully narrow a search, or is it so common it could describe ten thousand photos?

SCAN THE BACKGROUND: Actively look for geographic landmarks, named monuments, distinctive architecture, coastline formations, volcanic features, city skylines. If you can identify something with HIGH CONFIDENCE, include it by name (e.g. "Diamond Head crater", "Golden Gate Bridge", "Makapuu lighthouse"). If you are not certain, describe it generically instead ("volcanic crater", "suspension bridge") — do NOT guess proper names.

BANNED — never use these or any term equally broad:
water, ocean, sea, lake, river, sky, cloud, sun, tree, plant, flower, grass, ground, rock, stone, sand, beach, road, path, street, building, structure, wall, floor, ceiling, light, shadow, outdoor, indoor, scene, view, background, foreground, landscape, nature, color, white, black, blue, green, red, yellow, beautiful, stunning, amazing, photo, image, picture, camera

GOOD examples: "Diamond Head crater", "long-exposure waterfall", "taro lo'i", "lava bench", "outrigger canoe", "monsoon shelf cloud", "wet-plate portrait", "brutalist facade", "golden-hour sidelight", "aerial perspective"
BAD examples: "beach", "water", "blue sky", "palm tree", "mountain", "building", "landscape", "nature"

Use lowercase. Prefer two-word specific phrases over single generic words."""


# ── Curated model lists per cloud backend ─────────────────────────────────────

GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.5-flash-preview-04-17",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-2.5-pro-preview-05-06",
]

CLAUDE_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-opus-4-7",
]

OPENAI_MODELS = [
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4-turbo",
]

_OLLAMA_TIMEOUT = 180   # seconds; bump if your model is very large


# ── Ollama helpers ────────────────────────────────────────────────────────────

def list_available_models(host: str = "http://localhost:11434") -> List[str]:
    """Query Ollama for locally available models. Returns [] if unreachable."""
    try:
        client = ollama.Client(host=host, timeout=10)
        result = client.list()
        return sorted(m.model for m in result.models)
    except Exception:
        return []


def check_ollama_available(host: str = "http://localhost:11434") -> bool:
    try:
        ollama.Client(host=host, timeout=10).list()
        return True
    except Exception:
        return False


# ── Main dispatch ─────────────────────────────────────────────────────────────

def _build_prompt(context_hint: str) -> str:
    """Prepend optional user context so the model sees it before any constraints."""
    if not context_hint or not context_hint.strip():
        return CAPTION_PROMPT
    header = (
        f"SCENE LOCATION / PHOTOGRAPHER CONTEXT: {context_hint.strip()}\n"
        f"This tells you where and when these photos were taken. Use it to:\n"
        f"- Actively look in the background for any landmarks, locations, or features mentioned above\n"
        f"- If you can see a named landmark (e.g. 'Diamond Head crater'), name it in the caption and as a keyword\n"
        f"- Include location-specific terms that match what you can visually confirm\n"
        f"Context helps you CONFIRM — not fabricate. Only name things you can see.\n\n"
    )
    return header + CAPTION_PROMPT


def generate_caption(
    image_path: Path,
    settings,
    retries: int = 2,
) -> Tuple[str, List[str]]:
    """
    Generate a caption and keywords for image_path using the backend
    configured in settings. Raises RuntimeError on failure.
    """
    backend = getattr(settings, "backend", "ollama")
    max_kw  = getattr(settings, "max_keywords", 10)
    prompt  = _build_prompt(getattr(settings, "context_hint", ""))

    if backend == "gemini":
        return _generate_gemini(
            image_path, settings.gemini_api_key, settings.gemini_model, max_kw, retries, prompt
        )
    elif backend == "claude":
        return _generate_claude(
            image_path, settings.claude_api_key, settings.claude_model, max_kw, retries, prompt
        )
    elif backend == "openai":
        return _generate_openai(
            image_path, settings.openai_api_key, settings.openai_model, max_kw, retries, prompt
        )
    else:
        return _generate_ollama(
            image_path, settings.ollama_host, settings.ollama_model, max_kw, retries, prompt
        )


# ── Ollama (local) ────────────────────────────────────────────────────────────

def _generate_ollama(
    image_path: Path, host: str, model: str, max_keywords: int, retries: int, prompt: str
) -> Tuple[str, List[str]]:
    client = ollama.Client(host=host, timeout=_OLLAMA_TIMEOUT)
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            response = client.chat(
                model=model,
                messages=[{
                    "role": "user",
                    "content": prompt,
                    "images": [str(image_path)],
                }],
                format="json",
                options={"temperature": 0.3, "num_predict": 768},
            )
            return _parse_response(response.message.content.strip(), max_keywords)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            last_error = e
            if attempt < retries:
                time.sleep(1)
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(2)
    raise RuntimeError(
        f"Ollama caption failed after {retries + 1} attempts: {last_error}"
    )


# ── Google Gemini ─────────────────────────────────────────────────────────────

def _generate_gemini(
    image_path: Path, api_key: str, model: str, max_keywords: int, retries: int, prompt: str
) -> Tuple[str, List[str]]:
    try:
        from google import genai as google_genai
        from google.genai import types as genai_types
        _new_sdk = True
    except ImportError:
        _new_sdk = False

    if not _new_sdk:
        try:
            import google.generativeai as genai_old
            _new_sdk = None   # sentinel: old SDK available
        except ImportError:
            raise RuntimeError(
                "Gemini SDK not installed — run: pip install google-genai"
            )

    if not api_key:
        raise RuntimeError("Gemini API key is not set. Add it in Settings → AI Backend.")

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            if _new_sdk is True:
                # New google-genai SDK — supports response_mime_type (pure JSON, no markdown)
                client = google_genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model=model,
                    contents=[
                        genai_types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                        genai_types.Part.from_text(text=prompt),
                    ],
                    config=genai_types.GenerateContentConfig(
                        temperature=0.3,
                        max_output_tokens=768,
                        response_mime_type="application/json",
                    ),
                )
                text = response.text
            else:
                # Old google-generativeai SDK fallback
                genai_old.configure(api_key=api_key)
                gm = genai_old.GenerativeModel(model)
                blob = {"mime_type": "image/jpeg", "data": image_bytes}
                response = gm.generate_content(
                    [blob, prompt],
                    generation_config={
                        "temperature": 0.3,
                        "max_output_tokens": 768,
                        "response_mime_type": "application/json",
                    },
                )
                text = response.text
            return _parse_response(text.strip(), max_keywords)
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            if attempt < retries:
                time.sleep(1)
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(2)
    raise RuntimeError(
        f"Gemini caption failed after {retries + 1} attempts: {last_error}"
    )


# ── Anthropic Claude ──────────────────────────────────────────────────────────

def _generate_claude(
    image_path: Path, api_key: str, model: str, max_keywords: int, retries: int, prompt: str
) -> Tuple[str, List[str]]:
    try:
        import anthropic
    except ImportError:
        raise RuntimeError(
            "anthropic not installed — run: pip install anthropic"
        )
    if not api_key:
        raise RuntimeError("Claude API key is not set. Add it in Settings → AI Backend.")

    client = anthropic.Anthropic(api_key=api_key)
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            message = client.messages.create(
                model=model,
                max_tokens=768,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": img_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }],
            )
            return _parse_response(message.content[0].text.strip(), max_keywords)
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            if attempt < retries:
                time.sleep(1)
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(2)
    raise RuntimeError(
        f"Claude caption failed after {retries + 1} attempts: {last_error}"
    )


# ── OpenAI / ChatGPT ──────────────────────────────────────────────────────────

def _generate_openai(
    image_path: Path, api_key: str, model: str, max_keywords: int, retries: int, prompt: str
) -> Tuple[str, List[str]]:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError(
            "openai not installed — run: pip install openai"
        )
    if not api_key:
        raise RuntimeError("OpenAI API key is not set. Add it in Settings → AI Backend.")

    client = OpenAI(api_key=api_key)
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }],
                max_tokens=768,
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            return _parse_response(
                response.choices[0].message.content.strip(), max_keywords
            )
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            if attempt < retries:
                time.sleep(1)
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(2)
    raise RuntimeError(
        f"OpenAI caption failed after {retries + 1} attempts: {last_error}"
    )


# ── Response parser (shared by all backends) ──────────────────────────────────

def _parse_response(raw: str, max_keywords: int) -> Tuple[str, List[str]]:
    """Parse JSON caption response. Handles markdown fences and trailing commas."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()

    json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if json_match:
        cleaned = json_match.group(0)

    cleaned = re.sub(r",\s*([\]}])", r"\1", cleaned)

    data = json.loads(cleaned)

    caption = str(data.get("caption", "")).strip()
    if not caption:
        raise ValueError("Empty caption in model response")

    raw_kw = data.get("keywords", [])
    if isinstance(raw_kw, str):
        raw_kw = [raw_kw]

    BLOCKED = {"photo", "image", "photography", "picture", "photograph", "camera"}
    keywords: List[str] = []
    seen: set[str] = set()
    for kw in raw_kw:
        kw_clean = str(kw).strip().lower()
        if kw_clean and kw_clean not in BLOCKED and kw_clean not in seen:
            seen.add(kw_clean)
            keywords.append(str(kw).strip())
        if len(keywords) >= max_keywords:
            break

    return caption, keywords
