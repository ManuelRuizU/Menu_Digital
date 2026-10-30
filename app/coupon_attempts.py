# app/coupon_attempts.py
"""The coupon attempt log (CouponAttempt): written by the public menu endpoints, read by
the panel's "Uso de cupones". Anyone can write to it, so every value is checked against
a closed list and the code is cut to the column's size; rows older than RETENTION_DAYS
are deleted when the owner opens the panel view."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from app import db
from app.models import COUPON_ATTEMPT_RESULTS, COUPON_ATTEMPT_SOURCES, CouponAttempt

RETENTION_DAYS = 180
CODE_MAX = 30


def clean_code(code):
    return (code or '').strip().upper()[:CODE_MAX]


def clean_source(source):
    return source if source in COUPON_ATTEMPT_SOURCES else None


def log_attempt(code, source, result, reason=None):
    """Adds the row and commits. Ignored (False) without a code or with an unknown
    result; an unknown source is stored as NULL rather than dropping the row."""
    code = clean_code(code)
    if not code or result not in COUPON_ATTEMPT_RESULTS:
        return False
    db.session.add(CouponAttempt(code=code, source=clean_source(source), result=result,
                                 reason=(reason or None) and str(reason)[:20]))
    db.session.commit()
    return True


def purge_old(now=None):
    cutoff = (now or datetime.utcnow()) - timedelta(days=RETENTION_DAYS)
    deleted = CouponAttempt.query.filter(CouponAttempt.created_at < cutoff).delete(synchronize_session=False)
    db.session.commit()
    return deleted


def usage_summary(days=30, now=None):
    """{'codes': [{'code', 'by_source': {source: Counter(result)}, 'rejected_by_reason': Counter,
    'totals': Counter(result)}], 'reminder': Counter(result)} for the last `days` days,
    codes ordered by how many times they went out in an order, then by attempts."""
    since = (now or datetime.utcnow()) - timedelta(days=days)
    rows = CouponAttempt.query.filter(CouponAttempt.created_at >= since).all()
    by_code = defaultdict(lambda: {'by_source': defaultdict(Counter), 'rejected_by_reason': Counter(),
                                   'totals': Counter()})
    reminder = Counter()
    for row in rows:
        entry = by_code[row.code]
        entry['by_source'][row.source or 'unknown'][row.result] += 1
        entry['totals'][row.result] += 1
        if row.result == 'rejected':
            entry['rejected_by_reason'][row.reason or 'unknown'] += 1
        if row.source == 'reminder':
            reminder[row.result] += 1
    codes = [{'code': code, **entry} for code, entry in by_code.items()]
    codes.sort(key=lambda e: (-e['totals']['used'], -sum(e['totals'].values()), e['code']))
    return {'codes': codes, 'reminder': reminder, 'days': days}
