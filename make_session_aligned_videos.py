"""Build BORIS review videos from the common camera timestamp grid."""
import csv
import json
import subprocess
import argparse
from pathlib import Path
import numpy as np

ROOT = Path(r'D:\random_foraging\WT5_day13_outdoorLearnPM_090726')
OUT = ROOT / 'aligned_boris_review'
BIN = Path(r'C:\Users\Cornell\anaconda3\envs\campy\Library\bin')
CAMS = ['1b', '2b', '3b', '4b', '5b']

def expression(terms):
    if not terms:
        return '0'
    if len(terms)==1:
        return terms[0]
    mid=len(terms)//2
    return '('+expression(terms[:mid])+'+'+expression(terms[mid:])+')'

def probe(path, count=False):
    cmd = [str(BIN/'ffprobe.exe'), '-v', 'error', '-select_streams', 'v:0']
    if count:
        cmd += ['-count_frames']
    cmd += ['-show_entries', 'stream=nb_frames,nb_read_frames,width,height,avg_frame_rate,duration', '-of', 'json', str(path)]
    return json.loads(subprocess.check_output(cmd))['streams'][0]

def main():
    global ROOT, OUT, CAMS
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', type=Path, default=ROOT)
    parser.add_argument('--cameras', nargs='+', default=CAMS)
    parser.add_argument('--output-name', default='aligned_boris_review')
    args = parser.parse_args()
    ROOT, CAMS = args.session, args.cameras
    OUT = ROOT / args.output_name
    OUT.mkdir(exist_ok=False)
    data = {}
    for c in CAMS:
        with (ROOT/c/'frame_metadata.csv').open() as f:
            rows = list(csv.DictReader(f))
        t = np.array([float(r['cameraTimeStampSec']) for r in rows])
        d = np.diff(t)
        p = np.median(d[(d>.024)&(d<.026)])
        k = np.rint((t-t[1])/p).astype(int)+1
        fit = np.polyfit(k[1:5000], t[1:5000], 1)
        k = np.rint((t-fit[1])/fit[0]).astype(int)
        good = abs(t-(fit[0]*k+fit[1])) < .002
        fit = np.polyfit(k[good],t[good],1)
        k = np.rint((t-fit[1])/fit[0]).astype(int)
        residual = abs(t-(fit[0]*k+fit[1]))
        k -= k[0]
        assert np.all(np.diff(k)>0) and max(residual)<.002
        videos = list((ROOT/c).glob('*.mp4'))
        assert len(videos)==1
        info = probe(videos[0])
        assert int(info['nb_frames'])==len(rows)
        data[c] = dict(rows=rows, k=k, lookup={int(v):i for i,v in enumerate(k)},
                       video=videos[0], info=info, residual_ms=float(max(residual)*1000))
    common = sorted(set.intersection(*(set(data[c]['lookup']) for c in CAMS)))
    assert common
    print('Common frames:', len(common), 'last trigger:', common[-1], flush=True)
    with (OUT/'alignment.csv').open('w',newline='') as f:
        w=csv.writer(f)
        w.writerow(['output_frame_1based','video_time_sec','trigger_index_0based',CAMS[0]+'_host_arrival_time_NOT_exposure']+
                   [c+'_'+field for c in CAMS for field in ['saved_frame_1based','camera_frame_id','camera_timestamp_sec']])
        for outidx,k in enumerate(common):
            row=[outidx+1,format(outidx/40,'.3f'),k,data[CAMS[0]]['rows'][data[CAMS[0]]['lookup'][k]]['hostDateTimeIso']]
            for c in CAMS:
                r=data[c]['rows'][data[c]['lookup'][k]]
                row += [r['savedFrameNumber'],r['cameraFrameID'],r['cameraTimeStampSec']]
            w.writerow(row)
    (OUT/'README.txt').write_text(
        'BORIS alignment review: '+ROOT.name+'\n'
        'Each video contains {} frames at 40 fps ({} seconds).\n'.format(len(common),len(common)/40)+
        'Output frame N corresponds to the same inferred trigger in all videos.\n'
        'Camera clock rates were fitted independently. First saved frames are ASSUMED to share the first trigger; this is NOT independently verified.\n'
        'GPIO is not used to establish offsets for these cameras. PC arrival time is only a reference column, not the alignment basis.\n'
        'Manual visual verification is still needed; timestamp agreement does not independently prove exposure synchronization.\n'
        'Missing time points are removed from ALL cameras, so playback compresses real-time gaps.\n'
        'alignment.csv maps output frames to original saved frame numbers, camera IDs and timestamps. Frame numbers are 1-based; trigger indices are 0-based.\n'
        'Original resolution is retained; outputs are re-encoded H.264 without audio. Original recordings are unchanged.\n')
    summary={}
    for c in CAMS:
        x=data[c]
        keep=set(x['lookup'][k] for k in common)
        dropped=[i for i in range(len(x['rows'])) if i not in keep]
        ranges=[]
        for i in dropped:
            if ranges and i==ranges[-1][1]+1:
                ranges[-1][1]=i
            else:
                ranges.append([i,i])
        terms=['eq(n,{})'.format(a) if a==b else 'between(n,{},{})'.format(a,b) for a,b in ranges]
        script=OUT/(c+'_select.txt')
        script.write_text("select='not("+expression(terms)+")',setpts=N/(40*TB)")
        target=OUT/(c+'_aligned.mp4')
        cmd=[str(BIN/'ffmpeg.exe'),'-hide_banner','-nostdin','-n','-i',str(x['video']),
             '-filter_script:v',str(script),'-an','-c:v','h264_nvenc','-preset','fast','-rc','vbr',
             '-cq','18','-b:v','0','-pix_fmt','yuv420p','-r','40','-fps_mode','cfr','-movflags','+faststart',str(target)]
        print('Encoding',c,'keep',len(keep),'remove',len(dropped),flush=True)
        with (OUT/(c+'_encode.log')).open('w') as log:
            subprocess.run(cmd,stdout=log,stderr=log,check=True)
        print('Verifying decoded frame count',c,flush=True)
        result=probe(target,True)
        assert int(result['nb_read_frames'])==len(common),result
        assert int(result['nb_frames'])==len(common),result
        assert result['avg_frame_rate']=='40/1'
        assert (result['width'],result['height'])==(x['info']['width'],x['info']['height'])
        summary[c]=dict(output=result,removed=len(dropped),max_grid_residual_ms=x['residual_ms'])
        (OUT/'verification.json').write_text(json.dumps(summary,indent=2))
        print('VERIFIED',c,result,flush=True)
    print('COMPLETE',str(OUT),flush=True)

if __name__=='__main__':
    main()
