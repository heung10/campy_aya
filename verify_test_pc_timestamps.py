import csv
from pathlib import Path
import numpy as np
import sys

for name in (sys.argv[1:] or ['WT6_day14_outdoorMem_090826']):
    root=Path('D:/random_foraging')/name
    print('\nSESSION',name)
    data={}
    for c in ['1b','2b','3b','4b','5b']:
        with (root/c/'frame_metadata.csv').open() as f:
            rows=list(csv.DictReader(f))
        t=np.array([float(r['cameraTimeStampSec']) for r in rows])
        h=np.array([float(r['hostDateTimeEpochSec']) for r in rows])
        dt=np.diff(t)
        p=np.median(dt[(dt>.024)&(dt<.026)])
        k=np.rint((t-t[0])/p).astype(int)
        fit=np.polyfit(k[1:5000],t[1:5000],1)
        k=np.rint((t-fit[1])/fit[0]).astype(int)
        good=abs(t-(k*fit[0]+fit[1]))<.002
        fit=np.polyfit(k[good],t[good],1)
        k=np.rint((t-fit[1])/fit[0]).astype(int)
        e=t-(k*fit[0]+fit[1]);k-=k[0]
        data[c]=(rows,t,h,k)
        ids=np.array([int(r['cameraFrameID']) for r in rows])
        print(c,'frames',len(t),'first',rows[0]['hostDateTimeIso'],'last_index',k[-1],
              'residual_max_ms',round(max(abs(e))*1000,3),'residual_gt2ms',int(sum(abs(e)>.002)))
        print('DETAIL',c,'period_ms',fit[0]*1000,'camera_span',t[-1],'host_span',h[-1]-h[0],
              'last',rows[-1]['hostDateTimeIso'],'missing_internal',int(sum(np.maximum(np.diff(k)-1,0))),
              'id_missing',int(sum(np.maximum(np.diff(ids)-1,0))), 'gap_events',int(sum(np.diff(k)>1)),
              'nonmonotonic_grid',int(sum(np.diff(k)<=0)),'max_camera_gap_ms',max(dt)*1000)
    reference=max(data,key=lambda c:len(data[c][0]))
    rr,rt,rh,rk=data[reference]
    assert np.array_equal(rk,np.arange(len(rk))), 'Reference must have complete grid'
    print('REFERENCE',reference)
    for c in [c for c in data if c!=reference]:
        rows,t,h,k=data[c]
        print('PC comparisons',c,'minus',reference,'offset means candidate reference index = local index + offset')
        for offset in [-1,0,1]:
            ref=k+offset
            valid=(ref>=0)&(ref<len(rh))&(k<2000)
            delta=(h[valid]-rh[ref[valid]])*1000
            print(' offset',offset,'startup PC delta ms p10/median/p90',np.round(np.percentile(delta,[10,50,90]),3).tolist(),
                  'abs_delta_lt5ms',int(sum(abs(delta)<5)),'pairs',len(delta))
        valid=(k>=0)&(k<len(rh))
        delta=(h[valid]-rh[k[valid]])*1000
        print(' zero offset ALL PC delta ms p10/median/p90/p99',np.round(np.percentile(delta,[10,50,90,99]),3).tolist())
        print(' PC delta max_ms',round(max(delta),3),'last_ms',round(delta[-1],3))
        vv=np.flatnonzero(valid)
        for sec in [1,5,10]:
            ix=np.flatnonzero(delta>sec*1000)
            if len(ix):
                j=vv[ix[0]]
                print('DELAY_ONSET',c,sec,'sec received',rows[j]['hostDateTimeIso'],'reference',rr[k[j]]['hostDateTimeIso'])
        for a in [0,40,45,50,55]:
            ix=(k[valid]>=a*2400)&(k[valid]<(a+5)*2400)
            if any(ix):
                print('WINDOW',c,a,'min PC delta median/max sec',np.round(np.percentile(delta[ix]/1000,[50,100]),3).tolist())
        gaps=np.flatnonzero(np.diff(k)>1)
        print(' first gaps reference frame numbers assuming offset 0',[(int(k[i]+2),int(k[i+1]),rows[i]['hostDateTimeIso'],rows[i+1]['hostDateTimeIso']) for i in gaps[:5]])
        for i in gaps[:12]:
            print('GAP',c,'saved',i+1,'to',i+2,'IDs',rows[i]['cameraFrameID'],rows[i+1]['cameraFrameID'],
                  'camera_ms',round((t[i+1]-t[i])*1000,4),'PC_ms',round((h[i+1]-h[i])*1000,3))
            for j in range(max(0,i-2),min(len(rows),i+4)):
                nearest=int(np.argmin(abs(rh-h[j])))
                print(' frame',j+1,'grid_ref',k[j]+1,'PC_nearest_ref',nearest+1,'PC_delta_ms',round((h[j]-rh[nearest])*1000,3),'host',rows[j]['hostDateTimeIso'])
            for missing in range(int(k[i]+1),min(int(k[i+1]),int(k[i]+4))):
                print(' missing_ref',missing+1,'PC_reference_time',rr[missing]['hostDateTimeIso'])
        near=np.searchsorted(rh,h)
        hi=np.minimum(near,len(rh)-1);lo=np.maximum(near-1,0)
        nearest=np.where(abs(h-rh[lo])<=abs(h-rh[hi]),lo,hi)
        shifts,freq=np.unique(nearest-k,return_counts=True)
        print('PC_NEAREST index shift frequency',sorted(zip(shifts.tolist(),freq.tolist()),key=lambda x:-x[1])[:8])
    common=set.intersection(*(set(v[3]) for v in data.values()))
    print('common_count_zero_origin',len(common))
    if name=='multi_test16':
        print('ALL CAMERA first 4 rows')
        for c,(rows,t,h,k) in data.items():
            print(c,[(r['savedFrameNumber'],r['cameraTimeStampSec'],r['hostDateTimeIso']) for r in rows[:4]])
