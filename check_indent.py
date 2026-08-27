with open('src/gaming_news_digest/pipeline.py', 'rb') as f:
    content = f.read()

lines = content.split(b'\n')
for i in range(100, 120):
    if i < len(lines):
        line = lines[i]
        indent = len(line) - len(line.lstrip())
        print(f'Line {i}: {indent} spaces, len={len(lines[i])}, starts_with_space={line.startswith(b" ")}')