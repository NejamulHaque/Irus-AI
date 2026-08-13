try:
    from duckduckgo_search import DDGS
except ImportError:
    try:
        from ddgs import DDGS
    except ImportError:
        DDGS = None


def search_web(query, max_results=5):
    """
    Searches the live internet using DuckDuckGo (free, no API key).
    Returns a list of {title, url, snippet} dictionaries.
    """
    if DDGS is None:
        print("--- DEBUG: duckduckgo-search library not installed ---")
        return []

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))

        return [
            {
                'title': r.get('title', ''),
                'url': r.get('href', ''),
                'snippet': r.get('body', '')
            }
            for r in results
        ]
    except Exception as e:
        print(f"--- DEBUG: Web search failed: {e} ---")
        return []


def format_search_context(results):
    """
    Formats search results into a context block for the AI.
    """
    if not results:
        return ""

    blocks = []
    for i, r in enumerate(results, 1):
        blocks.append(
            f"[Source {i}] {r['title']}\nURL: {r['url']}\n{r['snippet']}"
        )

    return "\n\n".join(blocks)