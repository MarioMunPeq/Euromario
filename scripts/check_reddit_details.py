import json

d = json.load(open('frontend/data/news.json', 'r', encoding='utf-8'))
reddit = [i for i in d['news'] if i.get('source', {}).get('type') == 'reddit']
for i in reddit:
    sub = i['source'].get('subreddit', '?')
    print(f'  sub:       {sub}')
    print(f'  title:     {i["title"]}')
    print(f'  url:       {i["url"]}')
    print(f'  published: {i["published_at"]}')
    print(f'  game:      {i.get("game", "N/A")}')
    print(f'  id:        {i["id"]}')
    print()