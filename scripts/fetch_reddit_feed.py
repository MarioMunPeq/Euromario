"""Fetch Reddit Atom feed raw content."""
import sys

sys.path.insert(0, 'src')
from gaming_news_digest.fetchers.base import build_session, http_get

session = build_session()
url = "https://www.reddit.com/r/gamingleaks/new/.rss"
print(f"Fetching: {url}")
content = http_get(session, url, 15)
print(f"Length: {len(content)} bytes")
print("First 2000 chars:")
print(content[:2000])
print("\n...\nLast 500 chars:")
print(content[-500:])
