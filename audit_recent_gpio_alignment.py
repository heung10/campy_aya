"""Cross-check GPIO device timing against 1b; no source writes."""
import csv
import re
import numpy as np
from audit_recent_frame_timing import ROOT, OUT, writecsv

results=[]
for p in sorted(ROOT.iterdir()):
    if not re.match(r'WT[78]_day1[234]_',p.name) or 'calibration' in p.name.lower() or not (p/'1b/frame_metadata.csv').exists():
        continue
    with (p/'1b/frame_metadata.csv').open() as f:
        t=np.array([float(r['cameraTimeStampSec']) for r in csv.DictReader(f)])
    d=np.diff(t); period=np.median(d[(d>.024)&(d<.026)])
    k=np.r_[0,np.cumsum(np.rint(d/period).astype(int))]
    for file in sorted(p.glob('*GPIO*.txt')):
        ev=[]
        with file.open() as f:
            for line in f:
                m=re.search(r'DeviceMs: (\d+), Sequence: (\d+), Data: (\d+)',line)
                if m and m[3]=='0':ev.append((int(m[1]),int(m[2])))
        dev=np.array([e[0] for e in ev],dtype=np.int64)
        dd=np.diff(dev); gk=np.r_[0,np.cumsum(np.rint(dd/25.).astype(int))]
        n=min(len(t),len(dev))
        fit=np.polyfit((dev[:n]-dev[0])/1000.,t[:n],1)
        err=t[:n]-np.polyval(fit,(dev[:n]-dev[0])/1000.)
        mismatch=np.flatnonzero(k[:n]!=gk[:n])
        result=dict(session=p.name,entries=len(ev),reference_frames=len(t),ordinal_trigger_mismatches=len(mismatch),first_mismatch_saved_frame=int(mismatch[0]+1) if len(mismatch) else '',ordinal_fit_residual_max_ms=float(abs(err).max()*1000),gpio_device_short_intervals=int(sum(dd<12)),gpio_missing_slots=int(np.maximum(np.rint(dd/25.).astype(int)-1,0).sum()),gpio_gap_positions=[int(i+1) for i in np.flatnonzero(dd>37)],camera_gap_positions=[int(i+1) for i in np.flatnonzero(d>.0375)],gpio_short_events=[dict(row=int(i+1),device_delta_ms=int(dd[i])) for i in np.flatnonzero(dd<12)])
        results.append(result)
        print(result,flush=True)
writecsv(OUT/'gpio_alignment_checks.csv',results)
