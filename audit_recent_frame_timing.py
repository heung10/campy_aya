"""Read-only audit of October WT7/WT8 day 12-14 recordings; outputs locally."""
import csv
import json
import re
import subprocess
from pathlib import Path
from datetime import datetime
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(r'D:\random_foraging')
OUT = Path(__file__).resolve().parent / 'reports' / 'day12_14_timing_20261007'
PROBE = Path(r'C:\Users\Cornell\anaconda3\envs\campy\Library\bin\ffprobe.exe')
CAMS = ['1b', '3b', '4b', '5b']

def kv(path):
    return dict(csv.reader(path.open(newline=''))) if path.exists() else {}

def writecsv(path, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)

def camera(path):
    with (path/'frame_metadata.csv').open(newline='') as f:
        rows = list(csv.DictReader(f))
    t = np.array([float(r['cameraTimeStampSec']) for r in rows])
    h = np.array([float(r['hostTimeStampSec']) for r in rows])
    ids = np.array([int(r['cameraFrameID']) for r in rows], dtype=np.int64)
    d = np.diff(t)
    period = float(np.median(d[(d>.024)&(d<.026)]))
    steps = np.rint(d/period).astype(np.int64)
    k = np.r_[0, np.cumsum(steps)]
    fit = np.polyfit(k, t, 1)
    residual = t-np.polyval(fit,k)
    # A lower envelope estimates host/camera clock drift without fitting stalls.
    rawlag = h-t
    blocks = np.floor(t/30).astype(int)
    ix = []
    for b in np.unique(blocks):
        candidates = np.flatnonzero(blocks==b)
        ix.append(candidates[np.argmin(rawlag[candidates])])
    basefit = np.polyfit(t[ix],rawlag[ix],1)
    lag = rawlag-np.polyval(basefit,t)
    lag -= np.percentile(lag,1)
    idstep = np.diff(ids)
    wrap = (idstep<0)&(ids[:-1]>60000)&(ids[1:]<5000)
    idstep[wrap] += 65535
    meta = kv(path/'metadata.csv')
    videos = []
    for v in sorted(path.glob('*.mp4')):
        try:
            stream = json.loads(subprocess.check_output([str(PROBE),'-v','error','-select_streams','v:0','-show_entries','stream=nb_frames,duration,avg_frame_rate,width,height','-of','json',str(v)]))['streams'][0]
            videos.append(dict(file=v.name, **stream))
        except Exception as e:
            videos.append(dict(file=v.name,error=str(e)))
    s = dict(session=path.parent.name,camera=path.name,frames=len(t),first_host=rows[0]['hostDateTimeIso'],last_host=rows[-1]['hostDateTimeIso'],camera_span_s=float(t[-1]-t[0]),trigger_span=int(k[-1]+1),internal_missing=int(np.maximum(steps-1,0).sum()),gap_events=int(sum(steps>1)),largest_gap_frames=int(max(0,steps.max()-1)),nonpositive_steps=int(sum(steps<=0)),id_missing=int(np.maximum(idstep-1,0).sum()),id_nonpositive=int(sum(idstep<=0)),id_wraps=int(sum(wrap)),grid_residual_max_ms=float(abs(residual).max()*1000),interval_residual_max_ms=float(abs(d-steps*period).max()*1000),period_s=fit[0],lag_p99_s=float(np.percentile(lag,99)),lag_max_s=float(lag.max()),lag_last_s=float(lag[-1]),lag_over1s_frames=int(sum(lag>1)),writer_frames=kv(path/'writer_stats.csv').get('framesWritten'),video_frames=sum(int(v.get('nb_frames',0)) for v in videos),videos=videos)
    for field in ['cameraModel','cameraSerialNo','queueHighWaterMark','failedGrabCount','timeoutCount','otherErrorCount','frameIdGapCount','bufferSize','frameWidth','frameHeight','guiPreviewFrameRate','cameraExposureTimeInUs']:
        s[field] = meta.get(field)
    a = np.load(str(path/'frametimes.npy'),allow_pickle=True)
    s['frametimes_shape'] = list(a.shape)
    gaps = []
    for i in np.flatnonzero(steps>1):
        gaps.append(dict(session=path.parent.name,camera=path.name,before_saved_frame=i+1,after_saved_frame=i+2,first_missing_trigger=int(k[i]+1),last_missing_trigger=int(k[i+1]-1),missing=int(steps[i]-1),elapsed_s=float(t[i]),camera_gap_s=float(d[i]),id_step=int(idstep[i]),arrival_before=rows[i]['hostDateTimeIso'],arrival_after=rows[i+1]['hostDateTimeIso'],lag_before_s=float(lag[i]),lag_after_s=float(lag[i+1])))
    return s,gaps,dict(t=t,h=h,k=k,lag=lag,rows=rows)

def gpio(path, ref):
    pattern = re.compile(r'Time: ([\d\-: .]+), DeviceMs: (\d+), Sequence: (\d+), Data: (\d+)(?:, PcReceive: ([\d\-: .]+))?')
    events = []
    with path.open() as f:
        lines = 0
        for line in f:
            lines += 1
            m = pattern.search(line)
            if m:
                events.append((int(m[2]),int(m[3]),int(m[4]),m[5] or m[1]))
    out=[]
    for channel in sorted(set(e[2] for e in events)):
        ev=[e for e in events if e[2]==channel]
        dev=np.array([e[0] for e in ev],dtype=np.int64)
        seq=np.array([e[1] for e in ev],dtype=np.int64)
        ds=np.diff(seq); dd=np.diff(dev)
        first=datetime.fromisoformat(ev[0][3]); last=datetime.fromisoformat(ev[-1][3])
        out.append(dict(session=path.parent.name,file=path.name,channel=channel,entries=len(ev),unparsed_lines=lines-len(events),first_sequence=int(seq[0]),last_sequence=int(seq[-1]),sequence_missing=int(np.maximum(ds-1,0).sum()),sequence_nonpositive=int(sum(ds<=0)),sequence_gap_events=int(sum(ds>1)),device_gap_max_ms=int(dd.max()) if len(dd) else 0,device_nonpositive=int(sum(dd<=0)),first_host=str(first),last_host=str(last),start_vs_1b_s=(first-datetime.fromisoformat(ref['first_host'])).total_seconds(),end_vs_1b_s=(last-datetime.fromisoformat(ref['last_host'])).total_seconds(),entries_minus_1b=len(ev)-ref['frames']))
        if channel == 0:
            gsteps=np.rint(dd/25.0).astype(np.int64)
            gk=np.r_[0,np.cumsum(gsteps)]
            out[-1]['device_missing_trigger_slots']=int(np.maximum(gsteps-1,0).sum())
            out[-1]['device_intervals_under12ms']=int(sum(dd<12))
    return out

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    sessions=sorted(p for p in ROOT.iterdir() if p.is_dir() and re.match(r'WT[78]_day1[234]_',p.name) and 'calibration' not in p.name.lower())
    summary=[]; gaps=[]; gp=[]; skipped=[]
    fig,axes=plt.subplots(len(sessions),2,figsize=(15,3*len(sessions)),squeeze=False)
    for si,p in enumerate(sessions):
        if not (p/'1b/frame_metadata.csv').exists():
            skipped.append(p.name); axes[si,0].set_title(p.name+' (no recording)'); continue
        data={}; ss={}
        for c in CAMS:
            if not (p/c/'frame_metadata.csv').exists():
                skipped.append(p.name+'/'+c); continue
            s,g,x=camera(p/c); ss[c]=s; data[c]=x; gaps.extend(g)
        ref=data['1b']; rs=ss['1b']
        mapping=dict(reference_saved_frame=np.arange(1,len(ref['k'])+1),trigger_index=ref['k'])
        for c,x in data.items():
            s=ss[c]
            # Compare host elapsed times for the same inferred trigger, avoiding
            # independent camera-clock drift. First frames assumed common trigger.
            if c != '1b':
                x['lag']=x['h']-np.interp(x['k'],ref['k'],ref['h'])
                x['lag']-=np.median(x['lag'][:min(200,len(x['lag']))])
                s.update(lag_p99_s=float(np.percentile(x['lag'],99)),lag_max_s=float(x['lag'].max()),lag_last_s=float(x['lag'][-1]),lag_over1s_frames=int(sum(x['lag']>1)))
            for event in gaps:
                if event['session']==p.name and event['camera']==c:
                    event['lag_before_s']=float(x['lag'][event['before_saved_frame']-1])
                    event['lag_after_s']=float(x['lag'][event['after_saved_frame']-1])
            loc=np.searchsorted(x['k'],ref['k'])
            valid=loc<len(x['k'])
            valid[valid] &= x['k'][loc[valid]]==ref['k'][valid]
            mapped=np.zeros(len(ref['k']),dtype=np.int64)
            mapped[valid]=loc[valid]+1
            mapping[c+'_saved_frame']=mapped
            s['count_minus_1b']=s['frames']-rs['frames']
            s['end_trigger_minus_1b_assumed_common_start']=int(x['k'][-1]-ref['k'][-1])
            s['start_arrival_vs_1b_s']=(datetime.fromisoformat(s['first_host'])-datetime.fromisoformat(rs['first_host'])).total_seconds()
            s['missing_vs_1b_assumed_common_start']=int(len(np.setdiff1d(ref['k'],x['k'])))
            summary.append(s)
            inds=np.unique(np.r_[np.arange(0,len(x['t']),max(1,len(x['t'])//3000)),np.flatnonzero(np.diff(x['k'])>1),len(x['t'])-1]).astype(int)
            axes[si,0].plot(x['t'][inds]/60,(x['k']-np.arange(len(x['k'])))[inds],label=c)
            # Max per 1s time bucket preserves short arrival stalls in the plot.
            b=np.floor(x['t']).astype(int); starts=np.r_[0,np.flatnonzero(np.diff(b))+1]
            axes[si,1].plot(x['t'][starts]/60,np.maximum.reduceat(x['lag'],starts),label=c,lw=.8)
        np.savez_compressed(str(OUT/(p.name+'_preliminary_alignment.npz')),**mapping)
        for file in sorted(p.glob('*GPIO*.txt')):
            gp.extend(gpio(file,rs))
        axes[si,0].set_title(p.name); axes[si,1].set_title('Excess PC delivery lag vs 1b (1b: own clock baseline)')
        for ax in axes[si]:
            ax.grid(alpha=.25); ax.legend(); ax.set_xlabel('Minutes from first camera frame')
        axes[si,0].set_ylabel('Cumulative missing trigger slots'); axes[si,1].set_ylabel('Seconds')
        print(p.name,[(c,ss[c]['frames'],ss[c]['internal_missing'],round(ss[c]['lag_max_s'],2)) for c in data],flush=True)
    fig.tight_layout(); fig.savefig(str(OUT/'timing_overview.png'),dpi=120); plt.close(fig)
    writecsv(OUT/'camera_summary.csv',[{k:v for k,v in s.items() if k not in ['videos','frametimes_shape']} for s in summary])
    writecsv(OUT/'gap_events.csv',gaps); writecsv(OUT/'gpio_summary.csv',gp)
    (OUT/'audit.json').write_text(json.dumps(dict(cameras=summary,gaps=gaps,gpio=gp,skipped=skipped),indent=2,default=lambda v: v.item() if isinstance(v,np.generic) else str(v)))
    print('OUTPUT',str(OUT), 'SKIPPED',skipped)

if __name__=='__main__':
    main()
