"""One-command numerical reproduction plus publication PNG charts."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--quick',action='store_true')
parser.add_argument('--output',type=Path,default=Path('runs/reproduction'))
args=parser.parse_args()
env={**os.environ,'PYTHONPATH':str(root/'src'),'MPLCONFIGDIR':str(root/'runs/plot-cache')}
command=[sys.executable,'-m','swarmops.learning','--output',str(args.output)]
if args.quick:command.append('--quick')
subprocess.run(command,cwd=root,env=env,check=True)
subprocess.run([sys.executable,str(root/'scripts/render-scientific-plots.py'),'--results',str(args.output)],cwd=root,env=env,check=True)
