"""Render real exported simulation traces; this is not a web UI screenshot."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen
from PIL import Image, ImageDraw, ImageFont

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url', default='http://127.0.0.1:8766')
parser.add_argument('--output', type=Path, default=Path('docs/images/simulation.gif'))
args = parser.parse_args()
with urlopen(args.url + '/api/export/trace', timeout=5) as response:
    raw = response.read()
data = json.loads(raw)
scenario, runs = data['scenario'], data['runs']
scale, gap, top = 27, 32, 66
panel_width = scenario['width'] * scale
width, height = 2 * panel_width + 3 * gap, scenario['height'] * scale + top + 45
try:
    font = ImageFont.truetype('/System/Library/Fonts/Menlo.ttc', 12)
except OSError:
    font = ImageFont.load_default()
colors = ['#5ce8c5', '#70a7ff', '#ffbd70', '#d29cff', '#f38eab', '#a4da67', '#70d9ff', '#ffec8b']
frames = []
length = min(len(run['trace']) for run in runs)
if length < 2:
    raise SystemExit('Step or play the real simulation before rendering animation.')
for index in range(0, length, max(1, length // 50)):
    image = Image.new('RGB', (width, height), '#071319')
    draw = ImageDraw.Draw(image)
    draw.text((gap, 12), 'SWARMOPS | SIMULATION TRACE | no physical robots', font=font, fill='#c9dfe3')
    for side, run in enumerate(runs):
        frame = run['trace'][index]
        offset = gap + side * (panel_width + gap)
        completed = sum(value == 'completed' for value in frame['jobs'].values())
        draw.text((offset, 38), f"{run['policy']} | tick {frame['tick']} | delivered {completed}", font=font, fill='#8fe8cd')
        for x, y in scenario['walls']:
            draw.rounded_rectangle((offset+x*scale+2, top+y*scale+2, offset+(x+1)*scale-2, top+(y+1)*scale-2),
                                   radius=3, fill='#2c404b', outline='#54717b')
        for order in scenario['orders']:
            for x, y in (order['pickup'], order['delivery']):
                draw.rectangle((offset+x*scale+7, top+y*scale+7, offset+(x+1)*scale-7, top+(y+1)*scale-7),outline='#668f86')
        for robot in frame['robots']:
            x, y = robot['cell']; cx, cy = offset+(x+.5)*scale, top+(y+.5)*scale
            draw.ellipse((cx-9, cy-9, cx+9, cy+9), fill=colors[robot['id']%len(colors)])
            draw.text((cx-4, cy-7), str(robot['id']+1), font=font, fill='#071319')
    draw.text((gap, height-26), 'Generated from actual exported integer-tick positions; not an app-screen recording.', font=font, fill='#87a2ad')
    frames.append(image)
args.output.parent.mkdir(parents=True,exist_ok=True)
frames[0].save(args.output, save_all=True, append_images=frames[1:], duration=130, loop=0)
Path('results/animation.json').write_text(json.dumps({'frames':len(frames),'source_ticks':length,
    'source_trace_sha256':hashlib.sha256(raw).hexdigest(),'model_id':data['model_id'],
    'kind':'rendered recorded simulation trace; not UI recording'},indent=2)+'\n')
print(f'Saved {len(frames)} real-trace animation frames.')
