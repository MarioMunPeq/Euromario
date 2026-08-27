with open('src/gaming_news_digest/pipeline.py', 'rb') as f:
    content = f.read()
lines = content.split(b'\n')
for i in range(105, 120):
    if i < len(lines):
        line = lines[i]
        indent = len(line) - len(line.lstrip())
        hex_repr = line[:80].hex() if len(line) > 0 else 'empty'
        print(f'Line {i}: indent={indent}, len={len(line)}, hex={hex_repr}')