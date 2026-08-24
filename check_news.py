import json

with open('frontend/data/news.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

for i, item in enumerate(data['news']):
    print(f'{i+1}. {item["title"]}')
    print(f'   Source: {item["source"]["name"]} ({item["source"]["type"]})')
    print(f'   URL: {item["url"]}')
    print(f'   Game: {item["game"]}')
    print(f'   Category: {item["category"]}')
    print()