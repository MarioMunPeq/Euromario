import json
with open('frontend/data/news.json', 'r', encoding='utf-8') as f:
    d = json.load(f)
print(f'Total: {d["total"]}')
reddit = [i for i in d['news'] if i.get('source', {}).get('type') == 'reddit']
print(f'Reddit items: {len(reddit)}')
for i in reddit:
    print(f'  {i["title"][:60]} -> {i["url"]}')