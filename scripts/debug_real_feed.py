"""Debug feedparser on real Reddit feed."""
import feedparser

# Use the content we just fetched
content = open('scripts/reddit_gaming_feed.xml', 'rb').read()
parsed = feedparser.parse(content)

print(f"Bozo: {parsed.bozo}")
print(f"Entries: {len(parsed.entries)}")

for i, entry in enumerate(parsed.entries[:3]):
    print(f"\n--- Entry {i} ---")
    print(f"  title: {entry.get('title', '')[:80]}")
    print(f"  link:  {entry.get('link', '')}")
    print(f"  links: {entry.get('links', [])}")
    print(f"  id:    {entry.get('id', '')}")