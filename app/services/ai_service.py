import os
import re
import json

# ----------------------- Creator identity -----------------------
CREATOR_RE = re.compile(
    r"who\s+(made|created|built|developed|designed|programmed)\s+(you|irus)|"
    r"who\s+is\s+(your|the)\s+(creator|developer|maker|author)|"
    r"who\s+is\s+(Nejamul Haque|the\s+creator)|"
    r"who\s+is\s+(Nejamul Haque|the\s+developer)|"
    r"who\s+is\s+(Nejamul Haque|the\s+author)|"
    r"who\s+is\s+(Nejamul Haque|the\s+maker)|"
    r"who\s+is\s+(Nejamul Haque|the\s+designer)|"
    r"who\s+is\s+(Nejamul Haque|the\s+programmer)|"
    r"who\s+is\s+(Nejamul Haque|the\s+engineer)|"
    r"who\s+is\s+(Nejamul Haque|the\s+creator\s+of\s+irus)|"
    r"who\s+build\s+(you|irus)|(your|the)\s+creator",
    re.I
)
CREATOR_ANSWER = (
    "I was created by **Nejamul Haque** \n\n"
    "He is DevSecOps engineer who designed, built and deployed me end-to-end — the Flask backend, the AI pipelines, "
    "the DevSecOps pipeline, and the responsive PWA frontend you're using right now.\n\n"
    "If Irus helps you, consider supporting his work via the ☕ **Support** section!"
)

def creator_reply(text):
    if text and CREATOR_RE.search(text):
        return CREATOR_ANSWER
    return None

# ----------------------- Message building -----------------------
def build_messages(history, extra_context="", user_memories=None):
    system_prompt = (
        "You are Irus, a professional, friendly AI assistant. "
        "IDENTITY: You were created and built by Nejamul Haque. "
        "If anyone asks who made, created, built or developed you, answer: Nejamul Haque. "
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

# ----------------------- Multimodal helpers -----------------------
def _flatten_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return str(content)

def _image_parts(content):
    parts = []
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                url = part.get("image_url", {}).get("url", "")
                if url.startswith("data:") and "," in url:
                    header, b64 = url.split(",", 1)
                    mime = header.split(":")[1].split(";")[0] if ":" in header else "image/jpeg"
                    parts.append((mime, b64))
    return parts

# ----------------------- Providers -----------------------
GROQ_FALLBACK_MODELS = [
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-20b",
    "qwen/qwen3.6-27b",
    "groq/compound",
]

def _stream_groq(messages, model_override=None):
    from groq import Groq
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is missing")
    client = Groq(api_key=api_key)

    models_to_try = [model_override or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")]
    models_to_try += [m for m in GROQ_FALLBACK_MODELS if m not in models_to_try]

    last_err = None
    for model in models_to_try:
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=float(os.getenv("AI_TEMPERATURE", "0.7")),
                max_tokens=int(os.getenv("AI_MAX_TOKENS", "1024")),
                stream=True,
            )
            got = False
            for chunk in stream:
                delta = chunk.choices[0].delta
                if getattr(delta, "content", None):
                    got = True
                    yield delta.content
            return  # success
        except Exception as e:
            last_err = e
            print(f"--- [Groq] model '{model}' failed: {e} — trying next ---")
            if 'got' in dir() and got:
                raise  # never double-stream after partial output
            continue
    raise last_err or RuntimeError("All Groq models failed")

def _stream_gemini(messages):
    import requests
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY missing")
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    system_text = ""
    contents = []
    for m in messages:
        if m["role"] == "system":
            system_text = _flatten_text(m["content"]); continue
        parts = [{"text": _flatten_text(m["content"])}]
        for mime, b64 in _image_parts(m["content"]):
            parts.append({"inline_data": {"mime_type": mime, "data": b64}})
        contents.append({"role": "user" if m["role"] == "user" else "model", "parts": parts})
    payload = {"contents": contents}
    if system_text:
        payload["system_instruction"] = {"parts": [{"text": system_text}]}
    r = requests.post(url, json=payload, headers={"x-goog-api-key": key}, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"Gemini error {r.status_code}: {r.text[:300]}")
    out = r.json()["candidates"][0]["content"]["parts"][0].get("text", "")
    for i in range(0, len(out), 32):
        yield out[i:i + 32]

def _stream_openrouter(messages):
    import requests
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY missing")
    model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free")
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "stream": True},
        stream=True, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"OpenRouter error {r.status_code}: {r.text[:200]}")
    for line in r.iter_lines():
        if not line: continue
        line = line.decode()
        if line.startswith("data: "):
            data = line[6:]
            if data.strip() == "[DONE]": break
            try:
                delta = json.loads(data)["choices"][0]["delta"].get("content")
                if delta: yield delta
            except Exception:
                pass

def _stream_pollinations(messages):
    import requests
    try:
        r = requests.post("https://text.pollinations.ai/openai",
                          json={"model": "openai", "messages": messages}, timeout=120)
        if r.status_code != 200:
            raise RuntimeError(f"status {r.status_code}")
        out = r.json()["choices"][0]["message"]["content"]
    except Exception:
        text = _flatten_text(messages[-1]["content"]) if messages else "Hello"
        r = requests.get("https://text.pollinations.ai/" + requests.utils.quote(text), timeout=120)
        if r.status_code != 200:
            raise RuntimeError(f"Pollinations error {r.status_code}")
        out = r.text
    for i in range(0, len(out), 32):
        yield out[i:i + 32]

def _stream_ollama(messages, vision=False):
    import requests
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    if base.endswith("/v1"): base = base[:-3]
    model = os.getenv("OLLAMA_VISION_MODEL" if vision else "OLLAMA_MODEL", "llama3.2")
    flat = []
    for m in messages:
        entry = {"role": m["role"], "content": _flatten_text(m["content"])}
        if vision:
            b64s = [b for _, b in _image_parts(m["content"])]
            if b64s: entry["images"] = b64s
        flat.append(entry)
    with requests.post(f"{base}/api/chat", json={"model": model, "messages": flat, "stream": True},
                       stream=True, timeout=180) as r:
        if r.status_code != 200:
            raise RuntimeError(f"Ollama error {r.status_code}: {r.text[:300]}")
        for line in r.iter_lines():
            if line:
                c = json.loads(line).get("message", {}).get("content")
                if c: yield c

# ----------------------- Cloud-safe fallback chain -----------------------
def stream_chat(messages, model_override=None):
    provider = os.getenv("AI_PROVIDER", "groq").lower()
    fallback = os.getenv("FALLBACK_PROVIDER", "").lower()
    has_image = any(_image_parts(m["content"]) for m in messages)

    order = [provider]
    if has_image and os.getenv("GEMINI_API_KEY"): order.append("gemini")
    if os.getenv("GEMINI_API_KEY") and "gemini" not in order: order.append("gemini")
    if os.getenv("OPENROUTER_API_KEY"): order.append("openrouter")
    if fallback and fallback not in order: order.append(fallback)
    if "pollinations" not in order: order.append("pollinations")
    if "ollama" not in order: order.append("ollama")

    last_error = None
    for i, p in enumerate(order):
        started = False
        try:
            if p == "groq": gen = _stream_groq(messages, model_override)
            elif p == "gemini": gen = _stream_gemini(messages)
            elif p == "openrouter": gen = _stream_openrouter(messages)
            elif p == "pollinations": gen = _stream_pollinations(messages)
            elif p == "ollama": gen = _stream_ollama(messages, vision=has_image)
            else: continue
            for chunk in gen:
                started = True
                yield chunk
            return
        except Exception as e:
            last_error = e
            print(f"--- [AI] {p} failed: {e} ---")
            if started: raise
            if i < len(order) - 1:
                print(f"[Warning: {p} failed. Trying fallback: {order[i + 1]}]")
    if last_error:
        raise last_error