import os
import json
import requests

SYSTEM_PROMPT = """
You are Irus, a professional AI assistant.

Your rules:
- Be helpful, clear, and professional.
- Use Markdown when useful.
- Use code blocks for code.
- Be concise but informative.
- If you do not know something, say honestly that you do not know.
""".strip()

def build_messages(history_messages, extra_context="", user_memories=None):
    """
    Builds the message list for the AI.
    Injects user memories and document context into the system prompt.
    """
    system_content = SYSTEM_PROMPT
    
    # Inject Memories
    if user_memories:
        memory_text = "\n".join([f"- {m}" for m in user_memories])
        system_content += f"\n\n[USER MEMORIES]\n{memory_text}\n[END OF MEMORIES]\nUse these memories to personalize your responses."
        
    # Inject Document Context (RAG)
    if extra_context:
        system_content += f"\n\n{extra_context}"
        
    return [{"role": "system", "content": system_content}] + history_messages


def stream_chat(messages, model_override=None):
    provider = os.getenv("AI_PROVIDER", "groq").lower()
    fallback = os.getenv("FALLBACK_PROVIDER", "").lower()
    started = False

    try:
        if provider == "groq":
            for chunk in _stream_groq(messages, model_override):
                started = True
                yield chunk
        elif provider == "ollama":
            for chunk in _stream_ollama(messages):
                started = True
                yield chunk
        else:
            raise ValueError(f"Unknown AI_PROVIDER: {provider}")

    except Exception as e:
        if not started and fallback and fallback != provider:
            yield f"[Warning: {provider} failed. Trying fallback: {fallback}]\n"
            try:
                if fallback == "groq":
                    yield from _stream_groq(messages)
                elif fallback == "ollama":
                    yield from _stream_ollama(messages)
                else:
                    yield f"[AI fallback error] Unknown fallback provider: {fallback}"
            except Exception as fallback_error:
                yield f"[AI fallback error] {fallback_error}"
        else:
            yield f"[AI error] {e}"


def _stream_groq(messages, model_override=None):
    from groq import Groq
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is missing in .env")

    client = Groq(api_key=api_key)
    
    # Use the user's preferred model, or fallback to .env
    model = model_override or os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    
    temperature = float(os.getenv("AI_TEMPERATURE", "0.7"))
    max_tokens = int(os.getenv("AI_MAX_TOKENS", "1024"))

    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True
    )

    for chunk in stream:
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        delta = choice.delta
        if delta and delta.content:
            yield delta.content


def _stream_ollama(messages):
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    url = f"{base_url}/api/chat"

    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    temperature = float(os.getenv("AI_TEMPERATURE", "0.7"))
    max_tokens = int(os.getenv("AI_MAX_TOKENS", "1024"))

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens
        }
    }

    try:
        response = requests.post(url, json=payload, stream=True, timeout=(10, 300))
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Cannot connect to Ollama.")

    if response.status_code != 200:
        raise RuntimeError(f"Ollama error {response.status_code}: {response.text[:200]}")

    for line in response.iter_lines():
        if not line:
            continue
        try:
            data = json.loads(line.decode("utf-8"))
        except json.JSONDecodeError:
            continue
        if data.get("done"):
            break
        content = data.get("message", {}).get("content")
        if content:
            yield content