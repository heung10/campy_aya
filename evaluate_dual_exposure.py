import csv,re,json,subprocess
from pathlib import Path
from datetime import datetime
import numpy as np
root=Path('D:/campy_test/multi_test3')
pat=re.compile(r'Time: (.*?), DeviceMs: (\d+), Sequence: (\d+), Data: (\d+), PcReceive: (.*)')
ev=[]
for line in next(root.glob('WILD_GPIO*')).read_text().splitlines():
    m=pat.fullmatch(line)
    if m:
        a,d,s,ch,b=m.groups();ev.append((int(d),int(s),int(ch),datetime.fromisoformat(b).timestamp(),a))
print('GPIO',len(ev),'channels',sorted(set(e[2] for e in ev)),'sequence_gaps',sum(np.diff([e[1] for e in ev])!=1))
orig=ev[0][0];maps={}
reference_d=np.array([e[0] for e in ev if e[2]==0])
for c,ch in [('1b',0),('3b',2)]:
    e=[e for e in ev if e[2]==ch];d=np.array([e[0] for e in e])
    hi=np.minimum(np.searchsorted(reference_d,d),len(reference_d)-1);lo=np.maximum(hi-1,0)
    g=np.where(abs(d-reference_d[lo])<=abs(d-reference_d[hi]),lo,hi)
    maps[c]={int(k):int(v) for k,v in zip(g,d)}
    rows=list(csv.DictReader((root/c/'frame_metadata.csv').open()))
    t=np.array([float(r['cameraTimeStampSec']) for r in rows]);h=np.array([float(r['hostDateTimeEpochSec']) for r in rows]);ids=np.array([int(r['cameraFrameID']) for r in rows])
    dt=np.diff(t);p=np.median(dt[(dt>.024)&(dt<.026)]);k=np.rint(t/p).astype(int)
    print(c,'frames',len(rows),'gpio',len(e),'grid_first_last',k[0],k[-1],g[0],g[-1],'gpio_duplicates',len(g)-len(set(g)), 'GPIO_missing_grid',sorted(set(range(g[-1]+1))-set(g)))
    print('camera_missing_grid',sorted(set(range(k[-1]+1))-set(k)))
    print('gpio_without_frame',sorted(set(g)-set(k)),'frame_without_gpio',sorted(set(k)-set(g)))
    for i in np.flatnonzero(np.diff(k)>1):
        print('GAP saved',i+1,i+2,'IDs',ids[i],ids[i+1],'cam_ms',dt[i]*1000,'PC_ms',(h[i+1]-h[i])*1000,'time',rows[i]['hostDateTimeIso'])
    indices={int(v):i for i,v in enumerate(g)};sel=np.array([i for i,v in enumerate(k) if v in indices]);ii=np.array([indices[k[i]] for i in sel]);x=(d[ii]-orig)/1000.
    fit=np.polyfit(x,t[sel],1);res=(t[sel]-np.polyval(fit,x))*1000
    print('camera_device_fit_residual_ms',np.percentile(res,[0,50,100]).tolist(),'PC_minus_GPIO_receive_ms',np.percentile((h[sel]-np.array([e[j][3] for j in ii]))*1000,[0,50,99,100]).tolist())
    print('FIRST_LAST',rows[0]['hostDateTimeIso'],rows[-1]['hostDateTimeIso'])
    meta=dict(csv.reader((root/c/'metadata.csv').open()));print('stats',{v:meta.get(v) for v in ['failedGrabCount','timeoutCount','frameIdGapCount','queueHighWaterMark']})
    video=next((root/c).glob('*.mp4'));print('mp4',subprocess.check_output([r'C:\Users\Cornell\anaconda3\envs\campy\Library\bin\ffprobe.exe','-v','error','-select_streams','v:0','-show_entries','stream=nb_frames,duration,avg_frame_rate','-of','csv=p=0',str(video)]).decode().strip())
common=sorted(set(maps['1b'])&set(maps['3b']));delta=np.array([maps['3b'][k]-maps['1b'][k] for k in common]);print('EXPOSURE PAIRS',len(common),'delta_ms_hist',np.unique(delta,return_counts=True))
