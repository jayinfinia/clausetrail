import hmac
from fastapi import HTTPException, Request
from backend import config

USERS = {
    'alex': {'id': 'alex', 'name': 'Alex Morgan', 'role': 'reviewer', 'groups': ['research', 'legal']},
    'sam': {'id': 'sam', 'name': 'Sam Rivera', 'role': 'viewer', 'groups': ['research']},
    'jordan': {'id': 'jordan', 'name': 'Jordan Lee', 'role': 'admin', 'groups': ['legal']},
}

def user(request: Request):
    identity = USERS.get(request.session.get('user'))
    if not identity:
        raise HTTPException(401, 'Sign in to the fictional demo')
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        expected = request.session.get('csrf', '')
        supplied = request.headers.get('x-csrf-token', '')
        if not expected or not hmac.compare_digest(expected, supplied):
            raise HTTPException(403, 'Invalid session request token')
    return identity

def reviewer(request: Request):
    identity = user(request)
    if identity['role'] not in ('reviewer', 'admin'):
        raise HTTPException(403, 'Reviewer access required')
    return identity

def visible(record, identity):
    return record is not None and not record.deleted and record.scope in identity['groups']

def require_record(db, record_id, identity, lock=False):
    from sqlalchemy import select
    from backend.db import Record
    query = select(Record).where(Record.id == record_id)
    if lock:
        query = query.with_for_update()
    record = db.scalar(query)
    if not visible(record, identity):
        raise HTTPException(404, 'Agreement not found')
    return record
