"""Browser and live-instance interaction. Sprint 08 (read) / 09 (write).

`inspect.py` needs no browser at all — the rescope moved version stamps and data
locations to REST, which is scriptable. What genuinely requires the browser is model
VALIDATION, which has no REST equivalent across any of the 30 APP_BUILDER paths, and
the one-time datatype bootstrap.

Per D12, every browser sequence begins by asking the operator to accompany the
session. That is a request for presence, not a per-click prompt.
"""
