import csv
from pathlib import Path
import numpy as np

root = Path(r'D:\random_foraging\WT5_day13_outdoorLearnPM_090726')
sets = {}
reference = None
for c in ['1b', '2b', '3b', '4b', '5b']:
    rows = list(csv.DictReader((root / c / 'frame_metadata.csv').open()))
    t = np.array([float(r['cameraTimeStampSec']) for r in rows])
    h = np.array([float(r['hostTimeStampSec']) for r in rows])
    ids = np.array([int(r['cameraFrameID']) for r in rows])
    d = np.diff(t)
    p = np.median(d[(d > .024) & (d < .026)])
    k = np.rint((t-t[1])/p).astype(int)+1
    fit = np.polyfit(k[1:5000], t[1:5000], 1)
    k = np.rint((t-fit[1])/fit[0]).astype(int)
    good = np.abs(t-(fit[0]*k+fit[1])) < .002
    fit = np.polyfit(k[good], t[good], 1)
    k = np.rint((t-fit[1])/fit[0]).astype(int)
    err = t-(fit[0]*k+fit[1])
    k -= k[0]
    sets[c] = set(k.tolist())
    if c == '1b':
        reference = rows
    lag = h-(t-t[0])*.025/fit[0]
    print(c, 'N', len(t), 'grid', k[0], k[-1], 'period', fit[0], 'residual_ms', np.percentile(abs(err)*1000, [50,99,100]), 'ambiguous_gt2ms', sum(abs(err)>.002), 'duplicates', sum(np.diff(k)==0), 'missing_inside', k[-1]-k[0]+1-len(set(k)), 'ID_missing', sum(np.maximum(np.diff(ids)-1,0)), 'lag_p50_p99_max_last', np.percentile(lag,[50,99,100]).tolist()+[lag[-1]], 'camera_span', t[-1])
    ix = np.where(np.diff(k)>1)[0]
    print('first_gaps', [(int(i+1),int(k[i]+1),int(k[i+1]-1),round(float(t[i]),3),rows[i]['hostDateTimeIso']) for i in ix[:8]])
    print('lag_samples', [(int(i+1),round(float(lag[i]),3),int(k[i])) for i in np.linspace(0,len(t)-1,7).astype(int)])
    if len(ix):
        first_missing = int(k[ix[0]]+1)
        print('first_missing_reference_frame', first_missing+1, 'reference_host_time', reference[first_missing]['hostDateTimeIso'])
    onset = np.flatnonzero(lag > 1)
    if len(onset):
        j = int(onset[0])
        print('first_delay_gt1s_received', rows[j]['hostDateTimeIso'], 'reference_capture_approx', reference[k[j]]['hostDateTimeIso'])
common = set.intersection(*sets.values())
print('intersection', len(common))
for c,s in sets.items():
    print(c, 'remove_for_intersection', len(s-common))
import re
lines = (root / 'WILD_GPIO_20260907_182815.txt').read_text().splitlines()
events = [re.search(r'DeviceMs: (\d+), Sequence: (\d+), Data: (\d+)', line) for line in lines]
events = [tuple(map(int,m.groups())) for m in events if m]
for channel in sorted(set(e[2] for e in events)):
    ev = [e for e in events if e[2] == channel]
    print('gpio',channel,'count',len(ev),'first',ev[0],'last',ev[-1],'device_interval_range',np.percentile(np.diff([e[0] for e in ev]),[0,50,100]))
