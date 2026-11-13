import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path
from sqlalchemy import select, update
from backend import config
from backend.db import Session, Job, Record, now, migrate
from backend.services.extraction import model_extract, validate_value
from backend import tagging
import os

STOP = threading.Event()

def process_one():
    with Session() as db:
        expired = now() - timedelta(minutes=5)
        db.execute(update(Job).where(Job.status=='running', Job.updated<expired).values(status='queued', error='lease_recovered'))
        exhausted=list(db.scalars(select(Job).where(Job.status=='queued',Job.attempts>=3)))
        for failed in exhausted:
            failed.status='failed'; failed.error='retry_limit_reached'
            record=db.get(Record,failed.record_id)
            if record and not record.deleted: record.status='failed'
        job = db.scalar(select(Job).where(Job.status=='queued', Job.attempts<3).order_by(Job.updated).with_for_update(skip_locked=True))
        if not job:
            db.commit()
            return False
        # Conditional claim also protects SQLite from competing workers.
        claimed = db.execute(update(Job).where(Job.id==job.id, Job.status=='queued').values(status='running', attempts=Job.attempts+1, updated=now()))
        if claimed.rowcount != 1:
            db.rollback()
            return False
        record = db.get(Record,job.record_id)
        jid, rid = job.id, job.record_id
        if not record or record.deleted:
            job.status='cancelled'
            db.commit()
            return True
        path, suffix = record.path, Path(record.filename).suffix.lower()
        filename, rel_path, labels = record.filename, record.rel_path or '', dict(record.labels or {})
        db.commit()
    try:
        with tempfile.TemporaryDirectory(dir=config.DATA/'tmp', prefix='job-') as tmp:
            working = Path(tmp)/('input'+suffix)
            shutil.copyfile(path,working)
            output = Path(tmp)/'parsed.json'
            subprocess.run([sys.executable,'-m','backend.services.parsers',str(working),suffix,str(output)], check=True, timeout=180, capture_output=True)
            parsed=json.loads(output.read_text())
            if 'error' in parsed:
                raise ValueError(parsed['error'])
            proposals=model_extract(parsed['blocks'])
            tag_labels, tag_info = None, None
            if tagging.enabled():
                private = os.getenv('PRIVATE_LOCAL','false').lower()=='true'
                if not tagging.allowed(labels, private):
                    tag_info = {'status':'skipped','reason':'Not sent to Claude: this real document was not redacted locally on import.'}
                else:
                    try:
                        claude_props, tag_labels = tagging.tag(parsed['blocks'], filename, rel_path, validate_value)
                        for field, prop in claude_props.items():
                            if proposals.get(field,{}).get('state') in (None,'unknown'):
                                proposals[field] = prop
                        tag_info = {'status':'done','model':tagging.model(),'fields':len(claude_props)}
                    except tagging.TaggingUnavailable as exc:
                        tag_info = {'status':'failed','reason':str(exc)}
        with Session() as db:
            job, record=db.get(Job,jid),db.get(Record,rid)
            if record and not record.deleted:
                record.blocks=parsed['blocks']; record.proposals=proposals; record.status='needs_review'
                if tag_info:
                    new_labels = tagging.merge_labels(record.labels, tag_labels) if tag_labels else dict(record.labels or {})
                    new_labels['tagging'] = tag_info; record.labels = new_labels
                job.status='completed'; job.error=''
            else:
                job.status='cancelled'
            job.updated=now(); db.commit()
    except Exception:
        with Session() as db:
            job,record=db.get(Job,jid),db.get(Record,rid)
            job.status='failed'; job.error='processing_failed_check_format_or_local_model'; job.updated=now()
            if record and not record.deleted:
                record.status='failed'
            db.commit()
    return True

def sweep():
    cutoff=time.time()-3600
    removed=0
    for path in (config.DATA/'tmp').iterdir():
        if path.stat().st_mtime < cutoff:
            if path.is_dir(): shutil.rmtree(path)
            else: path.unlink()
            removed+=1
    from backend.db import Batch
    with Session() as db:
        for batch in db.scalars(select(Batch).where(Batch.created < now()-timedelta(days=1),Batch.status=='preview')):
            batch.rows=[]; batch.changes=[]; batch.status='expired'
        db.commit()
    return removed

def run():
    while not STOP.is_set():
        try:
            process_one(); sweep()
        except Exception:
            pass  # Never log document contents or exception payloads.
        STOP.wait(1)

if __name__=='__main__':
    migrate(); run()
