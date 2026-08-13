import os
import json


# -----------------------
# Message building
# -----------------------

def build_messages(history, extra_context="", user_memories=None):
    system_prompt = (
        "You are Irus, a professional, friendly AI assistant. "
        "Answer clearly and concisely, using Markdown formatting when helpful. "
        "When live web results are provided, cite them like [Source 1]."
    )
    if user_memories:
        system_prompt += "\n\n[LONG-TERM MEMORY ABOUT THE USER]\n" + "\n".join(f"- {m}" for m in user_memories)
    if extra_context:
        system_prompt += "\n\n" + extra_context.strip()

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    return messages


# -----------------------
# Multimodal helpers
# -----------------------

def _flatten_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return str(content)


def _extract_images(content):
    images = []
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                url = part.get("image_url", {}).get("url", "")
                if url.startswith("data:") and "," in url:
                    images.append(url.split(",", 1)[1])
    return images


# -----------------------
# Groq (supports vision natively)
# -----------------------

def _stream_groq(messages, model_override=None):
    from groq import Groq

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is missing in .env")

    client = Groq(api_key=api_key)
    model = model_override or os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=float(os.getenv("AI_TEMPERATURE", "0.7")),
        max_tokens=int(os.getenv("AI_MAX_TOKENS", "1024")),
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta
        if getattr(delta, "content", None):
            yield delta.content


# -----------------------
# Ollama (vision only with a vision model)
# -----------------------

def _stream_ollama(messages):
    import requests

    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    model = os.getenv("OLLAMA_MODEL", "llama3.2")

    flat = []
    for m in messages:
        entry = {"role": m["role"], "content": _flatten_text(m["content"])}
        imgs = _extract_images(m["content"])
        if imgs:
            entry["images"] = imgs
        flat.append(entry)

    # Vision handling: use a vision model if configured, else strip images
    if any("images" in e for e in flat):
        vision_model = os.getenv("OLLAMA_VISION_MODEL", "").strip()
        if vision_model:
            model = vision_model
        else:
            for e in flat:
                e.pop("images", None)
            print("--- [AI] Ollama: no vision model configured (set OLLAMA_VISION_MODEL=llava). Answering from text only. ---")

    with requests.post(
        f"{base}/api/chat",
        json={"model": model, "messages": flat, "stream": True},
        stream=True,
        timeout=180
    ) as r:
        if r.status_code != 200:
            raise RuntimeError(f"Ollama error {r.status_code}: {r.text[:300]}")
        for line in r.iter_lines():
            if line:
                data = json.loads(line)
                content = data.get("message", {}).get("content")
                if content:
                    yield content


# -----------------------
# Main entry with fallback
# -----------------------

def stream_chat(messages, model_override=None):
    provider = os.getenv("AI_PROVIDER", "groq").lower()
    fallback = os.getenv("FALLBACK_PROVIDER", "").lower()
    order = [provider] + ([fallback] if fallback and fallback != provider else [])

    last_error = None
    for i, p in enumerate(order):
        started = False
        try:
            if p == "groq":
                gen = _stream_groq(messages, model_override)
            elif p == "ollama":
                gen = _stream_ollama(messages)
            else:
                continue

            for chunk in gen:
                started = True
                yield chunk
            return

        except Exception as e:
            last_error = e
            print(f"--- [AI] {p} failed: {e} ---")
            if started:
                raise
            if i < len(order) - 1:
                print(f"[Warning: {p} failed. Trying fallback: {order[i + 1]}]")

    if last_error:
        raise last_error