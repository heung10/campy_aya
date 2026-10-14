import csv,re
from pathlib import Path
from datetime import datetime
import numpy as np

root=Path('D:/random_foraging/WT5_day14_outdoorLearn_090826')
with (root/'1b/frame_metadata.csv').open() as f:
    rows=list(csv.DictReader(f))
t=np.array([float(r['cameraTimeStampSec']) for r in rows])
h=np.array([float(r['hostDateTimeEpochSec']) for r in rows])
pat=re.compile(r'Time: (.*?), DeviceMs: (\d+), Sequence: (\d+), Data: (\d+), PcReceive: (.*)')
events=[]
for line in next(root.glob('WILD_GPIO*')).read_text().splitlines():
    m=pat.fullmatch(line)
    if m:
        a,d,s,ch,b=m.groups()
        events.append((datetime.fromisoformat(a).timestamp(),int(d),int(s),int(ch),datetime.fromisoformat(b).timestamp(),a))
a=np.array([r[0] for r in events]);d=np.array([r[1] for r in events]);s=np.array([r[2] for r in events]);pc=np.array([r[4] for r in events])
print('GPIO count',len(events),'channels',set(r[3] for r in events),'seq_start_end',s[0],s[-1], 'seq_gaps',sum(np.diff(s)!=1))
print('GPIO intervals device_ms',np.unique(np.diff(d),return_counts=True))
print('spans camera/device/Time/PcReceive/framePC',t[-1],(d[-1]-d[0])/1000,a[-1]-a[0],pc[-1]-pc[0],h[-1]-h[0])
print('Time minus device elapsed ms range',np.percentile(((a-a[0])-(d-d[0])/1000)*1000,[0,50,100]))
print('PcReceive minus Time ms',np.percentile((pc-a)*1000,[0,1,50,99,100]))
print('camera gap',[(int(i+1),float(t[i+1]-t[i]),rows[i]['hostDateTimeIso']) for i in np.flatnonzero(np.diff(t)>.0375)])
print('GPIO long gaps',[(int(i),int(d[i+1]-d[i]),events[i][5],int(s[i+1]-s[i])) for i in np.flatnonzero(np.diff(d)>37)])
if len(t)==len(d):
    x=(d-d[0])/1000
    fit=np.polyfit(x,t,1);err=t-np.polyval(fit,x)
    print('ordinal pairing camera/device rate',fit[0],'residual_ms',np.percentile(err*1000,[0,1,50,99,100]))
    print('framePC minus GPIOreceive ms',np.percentile((h-pc)*1000,[0,1,50,99,100]))
    print('framePC minus GPIO Time ms',np.percentile((h-a)*1000,[0,1,50,99,100]))
for i in range(6):
    print('FIRST',i+1,'camera',t[i],'framePC',rows[i]['hostDateTimeIso'],'gpio',events[i])
