"""Debug what feedparser extracts from the Reddit fixture."""
import feedparser

FIXTURE = "tests/fixtures/reddit_sample.rss"
content = open(FIXTURE, "rb").read()
parsed = feedparser.parse(content)

print(f"Bozo: {parsed.bozo}")
print(f"Entries: {len(parsed.entries)}")

for i, entry in enumerate(parsed.entries):
    print(f"\n--- Entry {i} ---")
    print(f"  title: {entry.get('title', '')}")
    print(f"  link:  {entry.get('link', '')}")
    print(f"  links: {entry.get('links', [])}")
    print(f"  id:    {entry.get('id', '')}")