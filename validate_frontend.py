from pathlib import Path

frontend = Path('frontend')
files = ['index.html', 'css/style.css', 'js/app.js', 'data/news.json']

for f in files:
    path = frontend / f
    if path.exists():
        content = path.read_text(encoding='utf-8')
        print(f'OK {f}: {len(content)} chars')
    else:
        print(f'MISSING {f}')

html = (frontend / 'index.html').read_text(encoding='utf-8')
js = (frontend / 'js/app.js').read_text(encoding='utf-8')

checks = [
    ('Header meta count', 'id="header-count"' in html),
    ('Header meta updated', 'id="header-updated"' in html),
    ('State loading', 'id="state-loading"' in html),
    ('State error', 'id="state-error"' in html),
    ('State empty', 'id="state-empty"' in html),
    ('State content', 'id="news-list"' in html),
    ('State mutually exclusive', 'state:not([hidden])' in open('frontend/css/style.css', encoding='utf-8').read()),
    ('Header meta', 'class="header__meta"' in html),
    ('Error state', 'id="state-error"' in html),
    ('Empty state', 'id="state-empty"' in html),
    ('News card design', 'news-card__title' in open('frontend/css/style.css', encoding='utf-8').read()),
    ('Reddit SVG', 'REDDIT_SVG' in open('frontend/js/app.js', encoding='utf-8').read()),
    ('Error handling', 'fetchNews' in open('frontend/js/app.js', encoding='utf-8').read()),
    ('Empty state', 'id="state-empty"' in html),
    ('CONFIG.appTitle', 'CONFIG.appTitle' in open('frontend/js/app.js', encoding='utf-8').read()),
]

for label, check in checks:
    status = 'OK' if check else 'FAIL'
    print(f'{status} {label}')