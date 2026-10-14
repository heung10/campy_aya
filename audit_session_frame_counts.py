import csv
import json
from pathlib import Path
from datetime import datetime

root = Path('D:/random_foraging')
cutoff = datetime(2026, 9, 5)
sessions = {}
issues = []
for path in sorted(root.rglob('frame_metadata.csv')):
    if 'aligned_boris_review' in path.parts:
        continue
    try:
        with path.open(newline='') as f:
            reader = csv.DictReader(f)
            first = next(reader)
            start = datetime.fromisoformat(first['hostDateTimeIso'])
            if start < cutoff:
                continue
            count = 1 + sum(1 for _ in reader)
        camera = path.parent
        session = camera.parent
        def pairs(name):
            p = camera/name
            if not p.exists():
                return {}
            with p.open(newline='') as f:
                return dict(csv.reader(f))
        meta, writer = pairs('metadata.csv'), pairs('writer_stats.csv')
        item = dict(camera=camera.name, frames=count, start=start.isoformat(),
                    total=meta.get('totalFrames'), written=writer.get('framesWritten'))
        sessions.setdefault(str(session), []).append(item)
        for field in ['total','written']:
            if item[field] is not None and int(item[field]) != count:
                issues.append(dict(path=str(path), field=field, value=item[field], rows=count))
    except Exception as e:
        issues.append(dict(path=str(path), error=str(e)))

report=[]
for session, cameras in sessions.items():
    counts=[c['frames'] for c in cameras]
    report.append(dict(session=session, date=min(c['start'] for c in cameras)[:10],
                       cameras=cameras, difference=max(counts)-min(counts),
                       exceeds_100=len(cameras)>1 and max(counts)-min(counts)>100))
report.sort(key=lambda r:(r['date'],r['session']))
output=Path('session_frame_count_audit_20260905_onward.json')
output.write_text(json.dumps(dict(cutoff=str(cutoff),sessions=report,issues=issues),indent=2))
for r in report:
    print(('MATCH ' if r['exceeds_100'] else 'OK    ')+r['date']+' '+Path(r['session']).name+' '+
          ' '.join(c['camera']+'='+str(c['frames']) for c in r['cameras'])+' difference='+str(r['difference']))
print('TOTAL',len(report),'MATCHES',sum(r['exceeds_100'] for r in report),'ISSUES',json.dumps(issues))
print('REPORT',output.resolve())
