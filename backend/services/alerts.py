"""Expiration alert previews (weekly summary, urgent, past due).

Default rules: a weekly summary to the configured alert roles (config/taxonomy.json)
and agreement owners on Mondays at 8:00 AM; an urgent alert N days (default 14)
before expiration; a past-due alert the day after expiration while the agreement
is still marked active. This module builds previews only. Nothing is sent.
"""
from datetime import date, timedelta

from backend.domain.framework import ALERT_ROLES

RECIPIENT_KEYS = (*ALERT_ROLES, 'owner')
DEFAULTS = {'day': 1, 'time': '08:00', 'urgent': 14, 'pastDue': True,
            'rec': {k: True for k in RECIPIENT_KEYS}, 'extra': []}
DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
URGENT_CHOICES = (7, 14, 21, 30)
INACTIVE = ('Expired', 'Terminated')


def validate(settings):
    s = {**DEFAULTS, **(settings or {})}
    if not isinstance(s['day'], int) or not 0 <= s['day'] <= 6: raise ValueError('Day must be 0-6 (Sunday-Saturday)')
    if s['urgent'] not in URGENT_CHOICES: raise ValueError('Urgent alert must be 7, 14, 21 or 30 days')
    if not isinstance(s['pastDue'], bool): raise ValueError('Past-due must be true or false')
    if not (isinstance(s['time'], str) and len(s['time']) == 5 and s['time'][2] == ':'): raise ValueError('Time must be HH:MM')
    rec = {k: bool((s.get('rec') or {}).get(k, False)) for k in RECIPIENT_KEYS}
    extra = [str(e).strip()[:120] for e in (s.get('extra') or []) if str(e).strip()][:10]
    return {'day': s['day'], 'time': s['time'], 'urgent': s['urgent'], 'pastDue': s['pastDue'], 'rec': rec, 'extra': extra}


def next_weekly(settings, today):
    # Python weekday(): Monday=0; settings day: Sunday=0.
    target = (settings['day'] - 1) % 7
    return today + timedelta(days=(target - today.weekday()) % 7)


def recipients(settings, owners):
    out = []
    out += [role for role in ALERT_ROLES if settings['rec'].get(role)]
    if settings['rec']['owner']: out += sorted({o for o in owners if o})
    return out + settings['extra']


def preview(expirations, settings, today=None):
    """expirations: dicts with agreement_id, ref_id, counterparty, owner, date (ISO), days, status."""
    today = today or date.today()
    s = validate(settings)
    active = [e for e in expirations if e.get('status') not in INACTIVE]
    window = [e for e in active if 0 <= e['days'] <= 90]
    past = [e for e in active if e['days'] < 0]
    urgent = [e for e in active if 0 <= e['days'] <= s['urgent']]
    def line(e):
        when = f"expired {-e['days']} day(s) ago" if e['days'] < 0 else f"expires in {e['days']} day(s)"
        return f"{e.get('ref_id') or '—'} · {e['counterparty']} · {e['date']} ({when}) · owner {e.get('owner') or 'unassigned'}"
    weekly_body = ['Agreements expiring in the next 90 days:'] + [line(e) for e in window] or []
    if not window: weekly_body.append('None.')
    if s['pastDue']:
        weekly_body += ['', 'Past expiration and still marked active:'] + ([line(e) for e in past] or ['None.'])
    return {
        'settings': s,
        'weekly': {'send': f"{DAYS[s['day']]}s at {s['time']}", 'next': next_weekly(s, today).isoformat(),
                   'to': recipients(s, [e.get('owner') for e in window + past]),
                   'subject': f"Weekly agreement expirations: {len(window)} in 90 days, {len(past)} past due",
                   'body': '\n'.join(weekly_body)},
        'urgent': [{'to': recipients(s, [e.get('owner')]), 'send': (date.fromisoformat(e['date']) - timedelta(days=s['urgent'])).isoformat(),
                    'subject': f"Urgent: {e['counterparty']} agreement expires {e['date']}", 'body': line(e), 'agreement_id': e['agreement_id']} for e in urgent],
        'pastDue': [{'to': recipients(s, [e.get('owner')]), 'send': (date.fromisoformat(e['date']) + timedelta(days=1)).isoformat(),
                     'subject': f"Past due: {e['counterparty']} agreement expired {e['date']}", 'body': line(e), 'agreement_id': e['agreement_id']} for e in past] if s['pastDue'] else [],
        'sent': False,
    }
