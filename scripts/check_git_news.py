import json, sys, subprocess

# Check earliest commits
commits = ['16c3e04', '8df3568', 'b394be7', '8df3568']

for commit in commits:
    result = subprocess.run(['git', 'show', f'{commit}:frontend/data/news.json'], capture_output=True, text=True, cwd='C:\\Users\\Mario\\Documents\\PROYECTOS\\G-Patch-Notes')
    if result.returncode != 0:
        print(f'{commit}: FILE NOT FOUND')
        continue
    try:
        d = json.loads(result.stdout)
        reddit = [i for i in d['news'] if i.get('source', {}).get('type') == 'reddit']
        print(f'{commit}: {len(reddit)} reddit items')
        for i in reddit:
            print(f'    {i["title"][:50]} -> {i["url"]}')
    except Exception as e:
        print(f'{commit}: ERROR - {e}')