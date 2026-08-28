import json
import subprocess

result = subprocess.run(
    ['git', 'show', 'b33f482:frontend/data/news.json'],
    capture_output=True,
    text=True,
    cwd='C:\\Users\\Mario\\Documents\\PROYECTOS\\G-Patch-Notes',
    check=False,
)
d = json.loads(result.stdout)
reddit = [i for i in d['news'] if i.get('source', {}).get('type') == 'reddit']
print(f'Reddit items in remote: {len(reddit)}')
for i in reddit:
    print(f'  {i["title"][:60]} -> {i["url"]}')