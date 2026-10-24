"""A presentation figure generated entirely from the frozen evaluation CSV."""
import csv
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

root = Path(__file__).resolve().parents[1]
with (root/'results/ml-full/evaluation-runs.csv').open() as file:
    rows=list(csv.DictReader(file))
policies=('distance','congestion','learned')
labels=('Distance baseline','Congestion heuristic','Learned model')
colors=('#70a7ff','#ffbd70','#5ce8c5')
fig=plt.figure(figsize=(13.5,7.8),facecolor='#071319')
fig.text(.055,.94,'SWARMOPS  /  RESEARCH NOTES',color='#5ce8c5',fontsize=11,weight='bold')
fig.text(.055,.875,'Does learned dispatch improve the fleet?',color='#e7f0f1',fontsize=25,weight='bold')
fig.text(.055,.828,'270 policy runs  ·  90 shared scenarios  ·  fixed 180-tick horizons  ·  simulation only',color='#8ca8b5',fontsize=11)
totals={}
for index,(split,title,subtitle) in enumerate((('test','HELD-OUT SHELF LAYOUTS','2 layouts × 2 demand levels × 20 paired seeds'),('ood','TOPOLOGY + DEMAND STRESS','2 barrier layouts × 5 paired seeds; 8 robots'))):
    ax=fig.add_axes([.21,.475 if index==0 else .135,.72,.23],facecolor='#071319')
    values=[];released=[]
    for policy in policies:
        group=[r for r in rows if r['split']==split and r['policy']==policy]
        values.append(sum(int(r['completed']) for r in group));released.append(sum(int(r['released']) for r in group))
    totals[split]=dict(zip(policies,values))
    ax.barh(range(3),values,color=colors,height=.55)
    ax.set_yticks(range(3),labels,color='#bdcfd5',fontsize=11);ax.invert_yaxis()
    ax.set_xlim(0,max(released));ax.tick_params(axis='x',colors='#6e939f',labelsize=9,length=0)
    ax.tick_params(axis='y',length=0,pad=15)
    for spine in ax.spines.values():spine.set_visible(False)
    ax.grid(axis='x',color='#253c47',lw=.6);ax.set_axisbelow(True)
    for i,(value,total) in enumerate(zip(values,released)):
        ax.text(value+max(released)*.018,i,f'{value:,} / {total:,}',va='center',color='#e1edf0',fontsize=11,weight='bold')
    top=.752 if index==0 else .412
    fig.text(.055,top,title,color='#e7f0f1',fontsize=12,weight='bold')
    fig.text(.055,top-.028,subtitle,color='#7898a6',fontsize=10)
    diff1,diff2=values[2]-values[0],values[2]-values[1]
    ax.set_xlabel(f'Completed jobs  |  ML vs distance: {diff1:+,}  ·  ML vs congestion: {diff2:+,}',
                  color='#97b3bc',fontsize=10,labelpad=10)
fig.text(.055,.045,'Mixed evidence: no consistent ML advantage. Backlog and completed-only latency are reported alongside these counts.',color='#8ca8b5',fontsize=10)
fig.savefig(root/'docs/images/research-overview.png',dpi=160,facecolor=fig.get_facecolor())
plt.close(fig)
(root/'results/visual-summary.json').write_text(json.dumps({'source':'results/ml-full/evaluation-runs.csv','totals':totals,'policy_runs':len(rows)},indent=2)+'\n')
print('Saved measured research overview.')
