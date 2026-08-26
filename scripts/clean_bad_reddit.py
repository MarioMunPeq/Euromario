import json

# Load current news.json
with open('frontend/data/news.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print(f"Total items before: {data['total']}")

# Remove Reddit items with fake URLs (abc123, def456)
original_news = data['news']
cleaned_news = [
    item for item in original_news
    if not (item.get('source', {}).get('type') == 'reddit' and 
            ('abc123' in item.get('url', '') or 'def456' in item.get('url', '')))
]

removed = len(original_news) - len(cleaned_news)
print(f"Removed {removed} bad Reddit items")

data['news'] = cleaned_news
data['total'] = len(cleaned_news)

# Save back
with open('frontend/data/news.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"Total items after: {data['total']}")

# Verify remaining Reddit items
reddit_remaining = [i for i in cleaned_news if i.get('source', {}).get('type') == 'reddit']
print(f"Remaining Reddit items: {len(reddit_remaining)}")
for item in reddit_remaining:
    print(f"  {item['title'][:60]} -> {item['url']}")