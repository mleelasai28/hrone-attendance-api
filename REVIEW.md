# Code Review

This review compares the supplied starter implementation in `candidate_kit/app/main.py` with `openapi.yaml`, `DATA_MODEL.md`, and the R1–R10 rules in the problem statement. Locations below refer to the starter file unless noted. The current implementation addresses these starter defects; endpoint smoke tests do not replace edge-case testing.

## Defects found and fixes made

1. **Health probe did not check MongoDB** — starter `health()` returned `{"status":"ok"}` unconditionally. A dead database therefore looked healthy. Fixed by issuing `db.command("ping")` and returning 503 on failure.
2. **Employee creation used a check-then-insert race** — starter `create_employee()` called `find_one()` before insert, so concurrent requests could both pass the check. Fixed with a unique `emp_code` index and handling `DuplicateKeyError` as 409.
3. **Employee creation omitted server timestamp serialization** — starter used naive `datetime.now()` and returned a different shape from the epoch-millisecond contract. Fixed by storing UTC time and serializing `created_at` as epoch milliseconds.
4. **Employee list skipped the wrong number of records** — starter used `skip = page * page_size`, which makes page 1 skip page 1's records. Fixed to `(page - 1) * page_size` and validated page/page_size bounds.
5. **Employee list total ignored filters** — starter used `count_documents({})`, so department-filtered pages reported the unfiltered total. Fixed to count the same query used for listing.
6. **Employee list was not deterministically sorted** — starter had no sort, so pagination could shift between requests. Fixed by sorting on `emp_code` ascending.
7. **Attendance listing loaded the whole collection into Python** — starter called `find(q)` without skip/limit, sorted all records in memory, then sliced. Fixed with MongoDB-side sort, skip, limit, and filtered count.
8. **Attendance list total was only the length of loaded records** — starter computed `total = len(docs)` after fetching all documents, making correct paging expensive. Fixed with `count_documents(q)` before fetching the requested page.
9. **Attendance date filters were not validated** — starter compared raw strings and did not reject malformed dates or `date_from > date_to`. Fixed with ISO date validation and 422 for reversed ranges.
10. **Punch-in did not check employee existence** — starter dereferenced `emp["shift_start"]` when employee lookup returned `None`, causing a server error. Fixed to return 404 for an unknown employee.
11. **Punch-in duplicate prevention was race-prone** — starter used a read-before-write duplicate check without a unique database constraint. Fixed with a unique compound index on `(emp_code, date)` and a 409 response for duplicate-key errors.
12. **Punch-in timestamps and attendance dates used host-local time** — starter used naive `datetime.fromtimestamp()` and `ts.date()`, which can assign the wrong IST date. Fixed by validating epoch milliseconds, converting to UTC/IST explicitly, truncating to whole seconds, and deriving the attendance date using shift rules.
13. **Late calculation ignored the employee attendance date and timezone** — starter `compute_late_minutes()` replaced the punch timestamp's clock fields and did not handle shifts across midnight correctly. Fixed to compare the punch instant with the shift start on the resolved attendance date, applying the strict 10-minute grace rule.
14. **Work-hour rounding used Python's default rounding** — starter `round(..., 2)` can use ties-to-even, unlike the half-up contract. Fixed with `Decimal` and `ROUND_HALF_UP`.
15. **Overtime calculation omitted the 30-minute threshold and overnight logic** — starter counted every positive minute and anchored shift end to a single naive date. Fixed to calculate the correct shift-end instant and return overtime only when at least 30 whole minutes accrue.
16. **Punch-out endpoint was missing** — the starter TODO explicitly listed it. Implemented punch-out lookup including the previous attendance date for overnight shifts, 24-hour validation, derived-field calculation, and conditional update to protect against concurrent punch-outs.
17. **Manual regularization and audit history were missing** — the starter TODO omitted PATCH handling. Implemented validation, recomputation of derived fields, optimistic concurrency checks, and append-only history entries recording actor, reason, timestamp, and actual field changes.
18. **Analytics endpoints were missing** — the starter TODO listed employee monthly, department summary, late leaderboard, and department trend. Implemented these using MongoDB aggregation pipelines, including zero-log headcount, competition ranking with ties, and a gap-filled daily trend.
19. **Database indexes were not created** — starter had no startup index setup. Added unique employee and attendance natural-key indexes plus query indexes for common filters/sorts and joined-date analytics.
20. **Request validation was too permissive** — starter models accepted unvalidated strings and timestamp values. Added Pydantic field validation for employee codes, email, shift times, ISO dates, epoch-millisecond timestamps, and pagination bounds.

## Verification recorded

- Health endpoint, employee create/list and duplicate handling, punch-in/punch-out, attendance listing, monthly analytics, department summary, late leaderboard, trend, and regularization were exercised during development.
- The five `/admin/explain/{endpoint}` variants were tested with sample data and each reported `uses_ixscan=True` and `uses_collscan=False` after the employee joined-date index was added.
- Department trend was checked for a seven-day range including weekend rows; it returned seven rows and null attendance rates on weekends.
- `python -m py_compile app/main.py` completed without output.

## Remaining test limits

These checks used the available local sample database, not a generated 100,000-record dataset. Concurrency races, all boundary instants, and large-scale latency still require dedicated automated tests. The explain flags are a summary of the returned plan and should be interpreted alongside raw explain output.
