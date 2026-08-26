import json

d = json.load(open('frontend/data/news.json', 'r', encoding='utf-8'))
reddit = [i for i in d['news'] if i.get('source', {}).get('type') == 'reddit']
print(f'Total Reddit items: {len(reddit)}')
for i in reddit:
    sub = i['source'].get('subreddit', '?')
    print(f'  sub:   {sub}')
    print(f'  title: {i["title"]}')
    print(f'  url:   {i["url"]}')
    print()