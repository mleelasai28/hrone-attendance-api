# Technical Decisions

1. **Indexes.** A unique `employees.emp_code` index enforces employee identity. A unique `(attendance_logs.emp_code, date)` index prevents duplicate employee-day records during concurrent punch-ins. `(emp_code, date)` supports employee-month queries; `(date, status)` supports common filters; `(date DESC, emp_code ASC)` supports attendance ordering. `(department, joined_on)` and `joined_on` support department and headcount queries. I rejected one wide index for every optional filter because it adds write cost without serving all combinations efficiently.

2. **Punch-in race.** Both requests may pass a lookup, but the unique index decides the outcome: one insert succeeds and the other raises `DuplicateKeyError`, converted to HTTP 409.

3. **Ties.** The leaderboard applies `$rank`, then filters `rank <= limit`. Cutoff ties are all returned, so results can exceed `limit`; rows sort by late minutes descending, then employee code ascending.

4. **Headcount.** Department summary starts from employees who joined by month end, groups by department, and looks up logs afterward. Employees with zero logs still count.

5. **100x scale.** I would benchmark 100,000-plus records and tune indexes from execution statistics. If analytics slow down, I would consider idempotently maintained daily summaries, keeping raw logs as source of truth.
