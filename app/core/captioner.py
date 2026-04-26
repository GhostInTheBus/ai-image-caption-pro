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

# ── Verbosity tables ──────────────────────────────────────────────────────────

# (keyword_range_text, max_keywords_hard_cap)
_KW_VERBOSITY: dict[int, tuple[str, int]] = {
    1: ("2–4 keywords only — the single most specific identifiers", 4),
    2: ("4–6 keywords", 6),
    3: ("5–8 keywords", 8),
    4: ("8–12 keywords", 12),
    5: ("12–20 keywords, covering every identifiable specific detail", 20),
}

# sentence-count instruction injected into the caption rule
_DESC_VERBOSITY: dict[int, str] = {
    1: "1 concise sentence",
    2: "1–2 sentences",
    3: "2–4 natural, readable sentences",
    4: "4–6 sentences",
    5: "6–8 sentences with thorough detail — foreground, background, light quality, texture, and any distinguishing character",
}


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

_OLLAMA_TIMEOUT = 600   # seconds; 72B models can take 5+ min on first load


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

def _build_prompt(
    context_hint: str = "",
    keyword_verbosity: int = 3,
    description_verbosity: int = 3,
    user_keywords: str = "",
    context_md: str = "",
) -> str:
    """Build the full prompt, injecting verbosity rules and optional context/seeds."""
    kw_rule, _ = _KW_VERBOSITY.get(keyword_verbosity, _KW_VERBOSITY[3])
    desc_rule   = _DESC_VERBOSITY.get(description_verbosity, _DESC_VERBOSITY[3])

    sections: List[str] = []

    # Photographer's brief (.md file — richest context, goes first)
    if context_md and context_md.strip():
        sections.append(
            f"PHOTOGRAPHER'S BRIEF — read this carefully before captioning. "
            f"Use it to deeply inform your vocabulary, style, named subjects, and keywords:\n\n"
            f"{context_md.strip()}"
        )

    # Optional context header
    if context_hint and context_hint.strip():
        sections.append(
            f"SCENE LOCATION / PHOTOGRAPHER CONTEXT: {context_hint.strip()}\n"
            f"This tells you where and when these photos were taken. Use it to:\n"
            f"- Actively look in the background for any landmarks, locations, or features mentioned above\n"
            f"- If you can see a named landmark (e.g. 'Diamond Head crater'), name it in the caption and as a keyword\n"
            f"- Include location-specific terms that match what you can visually confirm\n"
            f"Context helps you CONFIRM — not fabricate. Only name things you can see."
        )

    # Optional seed-keyword section
    if user_keywords and user_keywords.strip():
        seeds = [k.strip() for k in user_keywords.split(",") if k.strip()]
        if seeds:
            seed_list = ", ".join(f'"{s}"' for s in seeds)
            sections.append(
                f"REQUIRED KEYWORDS — provided by the photographer:\n"
                f"You MUST include ALL of the following in your keywords output, verbatim: {seed_list}\n"
                f"Add them alongside your own keywords — do not replace your analysis with only these."
            )

    # Core prompt (verbosity injected)
    core = (
        "You are a professional photo archivist building a long-term searchable image archive. "
        "Study this photograph carefully — foreground AND background — then respond ONLY with a valid JSON object. "
        "No markdown, no code fences, just raw JSON.\n\n"
        '{\n  "caption": "...",\n  "keywords": ["...", "..."]\n}\n\n'
        "CAPTION RULES\n"
        f"Write {desc_rule} as a knowledgeable observer would describe the image to someone who hasn't seen it. "
        "Cover what is in the foreground, what is visible in the background, the quality of light, and any detail that gives the image character. "
        "Name specific things you can identify with confidence. "
        'Do NOT start with "A photo of", "An image of", or "This image shows". '
        'Do NOT infer purpose, occasion, or relationships — no "vacation", "family outing", "tourist", "celebration", "wedding" — '
        "unless a sign or banner in the frame explicitly says so. "
        "Describe people by what they are doing and wearing, not who they might be or why they are there.\n\n"
        f"KEYWORD RULES — {kw_rule}\n"
        "Keywords must be specific and high-signal. Ask yourself: would this keyword meaningfully narrow a search, "
        "or is it so common it could describe ten thousand photos?\n\n"
        "SCAN THE BACKGROUND: Actively look for geographic landmarks, named monuments, distinctive architecture, "
        "coastline formations, volcanic features, city skylines. If you can identify something with HIGH CONFIDENCE, "
        'include it by name (e.g. "Diamond Head crater", "Golden Gate Bridge", "Makapuu lighthouse"). '
        'If you are not certain, describe it generically instead ("volcanic crater", "suspension bridge") — do NOT guess proper names.\n\n'
        "BANNED — these words are too generic to be useful as standalone keywords. Never use them alone:\n"
        "photo, image, picture, camera, photograph, photography, "
        "beautiful, stunning, amazing, gorgeous, "
        "outdoor, indoor, background, foreground, scene, view\n\n"
        "ALLOWED but only when specific: geographic/terrain words (desert, sand dune, lava field, salt flat) "
        "are fine when they describe a particular place or landform — just make them specific. "
        '"sand" alone is banned; "Mojave sand flat" or "black sand beach" is good.\n\n'
        'GOOD examples: "Diamond Head crater", "long-exposure waterfall", "taro lo\'i", "lava bench", "outrigger canoe", '
        '"monsoon shelf cloud", "wet-plate portrait", "brutalist facade", "golden-hour sidelight", "Mojave desert camp"\n'
        'BAD examples: "nature", "landscape", "beautiful", "photo", "image"\n\n'
        "If a PHOTOGRAPHER'S BRIEF is provided above, prioritise its named subjects, locations, and vocabulary in your keywords.\n\n"
        "Use lowercase. Prefer two-word specific phrases over single generic words."
    )
    sections.append(core)
    return "\n\n".join(sections)


def _merge_user_keywords(ai_keywords: List[str], user_kw_str: str) -> List[str]:
    """Prepend user seed keywords to AI keywords, deduplicating case-insensitively."""
    if not user_kw_str or not user_kw_str.strip():
        return ai_keywords
    seeds = [k.strip() for k in user_kw_str.split(",") if k.strip()]
    seen: set[str] = set()
    merged: List[str] = []
    for kw in seeds + ai_keywords:
        lower = kw.lower()
        if lower not in seen:
            seen.add(lower)
            merged.append(kw)
    return merged


def generate_caption(
    image_path: Path,
    settings,
    retries: int = 2,
    context_md: str = "",
) -> Tuple[str, List[str]]:
    """
    Generate a caption and keywords for image_path using the backend
    configured in settings. Raises RuntimeError on failure.
    """
    backend   = getattr(settings, "backend", "ollama")
    kw_verb   = getattr(settings, "keyword_verbosity", 3)
    desc_verb = getattr(settings, "description_verbosity", 3)
    user_kw   = getattr(settings, "user_keywords", "")
    _, max_kw = _KW_VERBOSITY.get(kw_verb, _KW_VERBOSITY[3])
    prompt    = _build_prompt(
        context_hint=getattr(settings, "context_hint", ""),
        keyword_verbosity=kw_verb,
        description_verbosity=desc_verb,
        user_keywords=user_kw,
        context_md=context_md,
    )

    if backend == "gemini":
        caption, keywords = _generate_gemini(
            image_path, settings.gemini_api_key, settings.gemini_model, max_kw, retries, prompt
        )
    elif backend == "claude":
        caption, keywords = _generate_claude(
            image_path, settings.claude_api_key, settings.claude_model, max_kw, retries, prompt
        )
    elif backend == "openai":
        caption, keywords = _generate_openai(
            image_path, settings.openai_api_key, settings.openai_model, max_kw, retries, prompt
        )
    else:
        caption, keywords = _generate_ollama(
            image_path, settings.ollama_host, settings.ollama_model, max_kw, retries, prompt
        )

    # Always guarantee user seed keywords appear in the output
    keywords = _merge_user_keywords(keywords, user_kw)
    return caption, keywords


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
