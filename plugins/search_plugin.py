"""Plugin: web search — delegates to tools/search.py."""
from tools.search import web_search, fetch_page_text
async def run(query: str):
    results = await web_search(query)
    if not results:
        return ""
    text = await fetch_page_text(results[0]["url"])
    return f"{results[0]['title']}: {text[:1500]}"
