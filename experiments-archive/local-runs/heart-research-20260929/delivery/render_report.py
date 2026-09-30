"""Render the report's used Markdown subset for local layout inspection."""
from pathlib import Path
import html
import json
import os
import re
import signal
import subprocess
import tempfile
import time

root = Path(__file__).resolve().parent.parent
lines = (root/'REPORT.md').read_text().splitlines()
output = []


def inline(text):
    text = html.escape(text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)',
                  lambda m: '<a href="'+m.group(2)+'">'+m.group(1)+'</a>', text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    return re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)


i = 0
while i < len(lines):
    line = lines[i]
    if not line.strip():
        i += 1
        continue
    if line.startswith('|'):
        group = []
        while i < len(lines) and lines[i].startswith('|'):
            group.append(lines[i]); i += 1
        cells = [row.strip('|').split('|') for row in group]
        assert all(len(row) == len(cells[0]) for row in cells)
        output.append('<table><thead><tr>'+''.join('<th>'+inline(c.strip())+'</th>' for c in cells[0])+'</tr></thead><tbody>')
        for row in cells[2:]:
            output.append('<tr>'+''.join('<td>'+inline(c.strip())+'</td>' for c in row)+'</tr>')
        output.append('</tbody></table>')
        continue
    if line.startswith('#'):
        n = len(line)-len(line.lstrip('#'))
        output.append(f'<h{n}>'+inline(line[n:].strip())+f'</h{n}>')
        i += 1
        continue
    if line.startswith('- '):
        output.append('<ul>')
        while i < len(lines) and lines[i].startswith('- '):
            output.append('<li>'+inline(lines[i][2:])+'</li>'); i += 1
        output.append('</ul>')
        continue
    output.append('<p>'+inline(line)+'</p>')
    i += 1

style = 'body{font:16px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;color:#19232e;max-width:1480px;margin:32px auto;padding:0 28px}h1{font-size:30px}h2{font-size:22px;margin-top:32px}table{border-collapse:collapse;width:100%;table-layout:fixed;font-size:14px}th,td{border:1px solid #cbd1d8;padding:10px;vertical-align:top;overflow-wrap:anywhere}th{background:#eaf0f4;text-align:left}code{font-size:.94em;color:#244f77;background:#f1f4f7}a{color:#246a9c}li{margin:9px 0}'
preview = root/'delivery/REPORT-preview.html'
preview.write_text('<!doctype html><meta charset="utf-8"><title>Heart research</title><style>'+style+'</style>'+''.join(output))
screenshot = root/'delivery/REPORT-preview.png'
screenshot.unlink(missing_ok=True)
with tempfile.TemporaryDirectory(prefix='heart-report-render-') as profile_dir, (root/'delivery/render.log').open('w') as log:
    args = ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '--headless=new',
            '--disable-gpu', '--disable-background-networking', '--disable-crash-reporter',
            '--no-first-run', '--no-default-browser-check', '--user-data-dir='+profile_dir,
            '--window-size=1600,2400', '--screenshot='+str(screenshot), preview.as_uri()]
    process = subprocess.Popen(args, stdout=log, stderr=log, start_new_session=True)
    try:
        deadline = time.monotonic()+30
        while not screenshot.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.1)
        assert screenshot.exists(), 'Chrome did not create a screenshot'
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            # Only this task-owned isolated browser process group.
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
assert screenshot.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
(root/'delivery/render-check.json').write_text(json.dumps(dict(screenshot_created=True,
    table_columns_consistent=True, browser_profile='isolated temporary profile; closed after screenshot'), indent=2))
print(screenshot)
