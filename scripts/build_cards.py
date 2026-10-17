"""Compose the dark and light profile cards from one layout spec.

The stats updater (today.py) only rewrites tspans by ID, so every stat ID and
its dot-leader sibling is emitted here with a data-width telling the updater
how many columns the value and its leader share. Running this script keeps
whatever numbers are already in dark_mode.svg.
"""
from __future__ import annotations

from html import escape
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'clover-terminal-v2'

W, H = 960, 560
FONT, LINE = 15, 20           # terminal text size and row pitch
COLS = 54                     # characters per terminal row
TERM_X, TERM_Y = 432, 82      # first terminal baseline
BAR = 22                      # churn bar cells

PALETTES = {
    'dark': dict(bg='#0d1117', chrome='#161b22', edge='#30363d', key='#ff7b86', value='#e6edf3',
                 cc='#6e7681', add='#3fb950', dele='#f85149', title='#8b949e', grid='#1a212b',
                 clover_top='#ff9aa3', clover_bottom='#d1293d', glow='#ff5f6d', sparkle='#ffd1d6',
                 lights=('#ff5f57', '#febc2e', '#28c840')),
    'light': dict(bg='#ffffff', chrome='#f6f8fa', edge='#d0d7de', key='#c4213a', value='#1f2328',
                  cc='#8c959f', add='#1a7f37', dele='#cf222e', title='#57606a', grid='#eef1f4',
                  clover_top='#e5485a', clover_bottom='#9e1a2c', glow='#e5485a', sparkle='#ff8a96',
                  lights=('#ff5f57', '#febc2e', '#28c840')),
}

DEFAULT_STATS = {'age_data': '5 years, 6 months, 28 days', 'repo_data': '14', 'contrib_data': '15',
                 'star_data': '9', 'commit_data': '122', 'follower_data': '11',
                 'loc_data': '85,943', 'loc_add': '94,992', 'loc_del': '9,049'}


# ---------------------------------------------------------------- terminal rows

def T(text, cls, **attrs):
    return (text, cls, attrs)


def leader(key, value, width, value_id=None):
    """`  key ..... value` spanning `width` columns, optionally updater-managed."""
    head = f'  {key}'
    region = width - len(head)            # dots + spaces + value
    count = region - 2 - len(value)
    dots = {0: '', 1: ' ', 2: '. '}.get(count, ' ' + '.' * max(count, 0) + ' ')
    dot_attrs, val_attrs = {}, {}
    if value_id:
        dot_attrs = {'id': f'{value_id}_dots', 'data-width': str(region - 2)}
        val_attrs = {'id': value_id}
    return [T(head, 'key'), T(dots, 'cc', **dot_attrs), T(value, 'value', **val_attrs)]


def section(name):
    return [T('─ ', 'cc'), T(name, 'key'), T(' ' + '─' * (COLS - len(name) - 3), 'cc')]


def pair(left, right):
    half = (COLS - 4) // 2
    return leader(left[0], left[1], half, *left[2:]) + [T('    ', 'cc')] + leader(right[0], right[1], half, *right[2:])


def rows(stats):
    churn_add = bar_cells(stats)
    return [
        [T('atul@github', 'key'), T(':~$ ', 'cc'), T('neofetch --clover', 'value cmd')],
        section('profile'),
        leader('os', 'Kali Linux, Windows 11', COLS),
        leader('uptime', stats['age_data'], COLS, 'age_data'),
        leader('role', 'Security Researcher | Red Teamer', COLS),
        leader('focus', 'Reverse Engineering, Exploit Dev', COLS),
        leader('editor', 'Neovim, VSCode', COLS),
        section('languages'),
        leader('programming', 'Rust, C, C++, Python', COLS),
        leader('scripting', 'Bash, PowerShell, JavaScript', COLS),
        leader('spoken', 'English, Hindi', COLS),
        section('offsec'),
        leader('craft', 'Malware Development, AV Evasion', COLS),
        leader('ranges', 'HackTheBox, Bug Bounty', COLS),
        section('contact'),
        pair(('htb', 'atulhack'), ('telegram', '@atulhacks')),
        pair(('linkedin', 'atulhack'), ('keybase', 'atulhack')),
        section('github'),
        pair(('repos', stats['repo_data'], 'repo_data'), ('contributed', stats['contrib_data'], 'contrib_data')),
        pair(('stars', stats['star_data'], 'star_data'), ('followers', stats['follower_data'], 'follower_data')),
        pair(('commits', stats['commit_data'], 'commit_data'), ('net loc', stats['loc_data'], 'loc_data')),
        [T('  churn ', 'key'),
         T('━' * churn_add, 'add', id='loc_bar_add', **{'data-cells': str(BAR)}),
         T('━' * (BAR - churn_add), 'del', id='loc_bar_del'),
         T('  +', 'add'), T(stats['loc_add'], 'add', id='loc_add'),
         T(' -', 'del'), T(stats['loc_del'], 'del', id='loc_del')],
        [T('atul@github', 'key'), T(':~$ ', 'cc')],
    ]


def bar_cells(stats):
    add, rem = (int(stats[k].replace(',', '')) for k in ('loc_add', 'loc_del'))
    return round(BAR * add / (add + rem)) if add + rem else BAR


def render_rows(stats):
    out = []
    for i, row in enumerate(rows(stats)):
        y = TERM_Y + i * LINE
        spans = ''.join(
            f'<tspan class="{cls}"{"".join(f" {k}={chr(34)}{v}{chr(34)}" for k, v in attrs.items())}>'
            f'{escape(text)}</tspan>' for text, cls, attrs in row)
        out.append(f'<text class="row" x="{TERM_X}" y="{y}" style="animation-delay:{0.95 + i * 0.045:.3f}s">'
                   f'{spans}</text>' if i else
                   f'<text class="prompt" x="{TERM_X}" y="{y}">{spans}</text>')
    return '\n'.join(out), TERM_Y + (len(out) - 1) * LINE


# ------------------------------------------------------------------- clover art

def clover_layers():
    grid = [line for line in (ROOT / 'assets/clover.txt').read_text().splitlines()
            if not line.startswith('#')]
    h, w = len(grid), len(grid[0])
    inside = [[ch != '.' for ch in row] for row in grid]
    # Breadth-first distance from the outline, through the interior only.
    dist = [[None] * w for _ in range(h)]
    frontier = [(y, x) for y in range(h) for x in range(w) if grid[y][x] == '#']
    for y, x in frontier:
        dist[y][x] = 0
    while frontier:
        nxt = []
        for y, x in frontier:
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and inside[ny][nx] and dist[ny][nx] is None:
                    dist[ny][nx] = dist[y][x] + 1
                    nxt.append((ny, nx))
        frontier = nxt
    layers = {name: [] for name in ('grid', 'fill', 'ink', 'sparkle')}
    for y, row in enumerate(grid):
        lines = {name: [' '] * w for name in layers}
        for x, ch in enumerate(row):
            d = dist[y][x]
            if ch == '.':
                if x % 2 == 0 and y % 2 == 0:
                    lines['grid'][x] = '·'
            elif ch == '+':
                lines['sparkle'][x] = '✦'
            elif d == 0:
                lines['ink'][x] = '◆'
            elif d is not None and d >= 2 and (x + y) % 2 == 0:
                lines['fill'][x] = '·'      # halftone body, kept off the outline
        for name in layers:
            layers[name].append(''.join(lines[name]).rstrip())
    return layers, w, h


def render_clover(p):
    layers, w, h = clover_layers()
    panel_x, panel_w = 24, 384
    cell = (panel_w - 24) / w            # glyph advance
    size = cell / 0.6
    pitch = size * 0.78
    x0 = panel_x + (panel_w - cell * w) / 2
    y0 = 60 + (H - 60 - pitch * h) / 2 - 12
    styles = {'grid': f'fill="{p["grid"]}"', 'ink': 'fill="url(#clover-fill)"',
              'fill': f'fill="{p["glow"]}" opacity=".35"', 'sparkle': f'fill="{p["sparkle"]}"'}
    classes = {'ink': 'clover-ink', 'fill': 'clover-glow', 'sparkle': 'sparkle'}

    def layer(name, extra=''):
        spans = ''.join(f'<tspan x="0" y="{(i + 1) * pitch:.2f}">{escape(line)}</tspan>'
                        for i, line in enumerate(layers[name]) if line)
        cls = f' class="{classes[name]}"' if name in classes else ''
        return f'<text{cls} font-size="{size:.2f}px" xml:space="preserve" {styles[name]}{extra}>{spans}</text>'

    body = '\n'.join(layer(n) for n in ('grid', 'fill', 'ink', 'sparkle'))
    scan_spans = layer('ink').replace('fill="url(#clover-fill)"', f'fill="{p["sparkle"]}"').replace(
        ' class="clover-ink"', '')
    top, bottom = y0, y0 + pitch * (h + 1)
    defs = (f'<linearGradient id="clover-fill" gradientUnits="userSpaceOnUse" x1="0" y1="{top:.0f}" '
            f'x2="0" y2="{bottom:.0f}"><stop offset="0" stop-color="{p["clover_top"]}"/>'
            f'<stop offset="1" stop-color="{p["clover_bottom"]}"/></linearGradient>'
            f'<clipPath id="scan-clip"><rect class="scan" x="{x0 - 4:.0f}" y="{top - 14:.0f}" '
            f'width="{cell * w + 8:.0f}" height="14"/></clipPath>')
    caption_y = bottom + 30
    art = (f'<g transform="translate({x0:.2f},{y0:.2f})">{body}</g>\n'
           f'<g clip-path="url(#scan-clip)" class="scanline" opacity=".8">'
           f'<g transform="translate({x0:.2f},{y0:.2f})">{scan_spans}</g></g>\n'
           f'<text x="{panel_x + panel_w / 2:.0f}" y="{caption_y:.0f}" text-anchor="middle" '
           f'font-size="13px" class="row" style="animation-delay:.6s">'
           f'<tspan class="cc">~/ </tspan><tspan class="value">grinding something</tspan></text>')
    return defs, art, (top, bottom)


# ------------------------------------------------------------------- assemble

def css(p, scan_span):
    top, bottom = scan_span
    travel = bottom - top + 28
    return f'''
.key{{fill:{p["key"]}}} .value{{fill:{p["value"]}}} .cc{{fill:{p["cc"]}}}
.add{{fill:{p["add"]}}} .del{{fill:{p["dele"]}}}
text,tspan{{white-space:pre}}
/* Motion lives inside the asset: no JavaScript, fonts, or network. */
.cmd{{animation:type .5s ease-out .25s both}}
.row{{animation:rise .5s cubic-bezier(.2,.7,.2,1) both}}
.clover-ink{{animation:breathe 6s ease-in-out infinite}}
.clover-glow{{animation:breathe 6s ease-in-out -3s infinite}}
.sparkle{{animation:twinkle 3.2s ease-in-out infinite}}
.scan{{animation:scan 9s cubic-bezier(.45,0,.55,1) 2s infinite}}
.cursor{{animation:blink 1.1s steps(1,end) infinite}}
@keyframes type{{from{{opacity:0}}to{{opacity:1}}}}
@keyframes rise{{from{{opacity:0;transform:translateY(5px)}}to{{opacity:1;transform:none}}}}
@keyframes breathe{{0%,100%{{opacity:.82}}50%{{opacity:1}}}}
@keyframes twinkle{{0%,100%{{opacity:.25}}50%{{opacity:1}}}}
@keyframes scan{{0%{{transform:translateY(0)}}28%,100%{{transform:translateY({travel:.0f}px)}}}}
@keyframes blink{{0%,49%{{opacity:1}}50%,100%{{opacity:0}}}}
@media (prefers-reduced-motion:reduce){{
  .cmd,.row,.clover-ink,.clover-glow,.sparkle,.scan,.cursor{{animation:none!important}}
  .scanline{{display:none}}
}}'''


def build(mode, stats):
    p = PALETTES[mode]
    clover_defs, art, scan_span = render_clover(p)
    terminal, last_y = render_rows(stats)
    cursor_x = TERM_X + len('atul@github:~$ ') * FONT * 0.6
    lights = ''.join(f'<circle cx="{24 + i * 20}" cy="20" r="6" fill="{c}"/>' for i, c in enumerate(p['lights']))
    return f'''<?xml version='1.0' encoding='utf-8'?>
<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace" font-size="{FONT}px" data-motion="{VERSION}">
<title>Atul — security researcher and reverse engineer</title>
<desc>A terminal window: an ASCII clover on the left, and on the right a neofetch-style profile with roles, languages, contacts, and daily-updated GitHub statistics.</desc>
<style>{css(p, scan_span)}
</style>
<defs>{clover_defs}<clipPath id="window"><rect width="{W}" height="{H}" rx="14"/></clipPath></defs>
<g clip-path="url(#window)">
<rect width="{W}" height="{H}" fill="{p["bg"]}"/>
<rect width="{W}" height="40" fill="{p["chrome"]}"/>
<line x1="0" y1="40.5" x2="{W}" y2="40.5" stroke="{p["edge"]}"/>
<line x1="420.5" y1="56" x2="420.5" y2="{H - 16}" stroke="{p["edge"]}" stroke-dasharray="2 4"/>
</g>
<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="14" fill="none" stroke="{p["edge"]}"/>
{lights}
<text x="{W / 2:.0f}" y="25" text-anchor="middle" font-size="12px" fill="{p["title"]}">atul@github: ~ — zsh — {COLS}×{H // LINE}</text>
{art}
{terminal}
<rect class="cursor" x="{cursor_x:.1f}" y="{last_y - 13}" width="9" height="16" fill="{p["key"]}"/>
</svg>
'''


def current_stats(path):
    stats = dict(DEFAULT_STATS)
    if path.exists():
        text = path.read_text()
        for key in stats:
            match = re.search(rf'id="{key}"[^>]*>([^<]*)<', text)
            if match:
                stats[key] = match.group(1)
    return stats


def main(root=ROOT):
    stats = current_stats(root / 'dark_mode.svg')
    for mode in PALETTES:
        (root / f'{mode}_mode.svg').write_text(build(mode, stats))


if __name__ == '__main__':
    main()
