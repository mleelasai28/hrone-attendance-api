# Technical Decisions

## 1. Indexing Strategy

Compound indexes support the most common query patterns, especially attendance lookups by employee and date, date-based analytics, and employee lookups by department. Index field order matters because MongoDB can efficiently use a compound index for queries matching its leading fields. The admin explain endpoint exposes execution statistics to help verify index usage.

## 2. Preventing Duplicate Punch-In

A unique compound index on `emp_code` and `date` prevents more than one attendance record for an employee on the same attendance date. Application-level checks alone are insufficient because simultaneous requests can both pass a check. The database constraint provides the final protection, and duplicate-key errors should be translated into an appropriate conflict response.

## 3. Leaderboard Ties

The late-arrival leaderboard uses competition ranking. Employees with equal total late minutes receive the same rank, and the next rank skips accordingly. The rank filter is applied before the result is limited, so employees tied at the cutoff are not arbitrarily excluded.

## 4. Employees Without Attendance Logs

Attendance-based aggregation alone cannot include employees who have no matching attendance records. To report department headcount accurately, employee records must be considered separately from attendance logs. Missing attendance statistics should be represented with zero values where appropriate, rather than removing employees from headcount calculations.

## 5. Scaling to 100 Times More Data

I would review query plans and execution statistics, maintain indexes for actual query patterns, and avoid unnecessary document retrieval. Aggregation pipelines should filter early where possible. For larger workloads, I would measure database load, consider archival or retention policies, and evaluate pagination and deployment capacity using representative production-scale data.

## Additional Technical Decisions

- FastAPI exposes REST endpoints and interactive API documentation.
- PyMongo provides access to MongoDB aggregation pipelines.
- Attendance dates use the Asia/Kolkata calendar, while API timestamps use epoch milliseconds and MongoDB stores timestamps as BSON datetimes.
- The department trend uses `$densify` for a daily date series and excludes weekends from working-day attendance rates.
- Department summary average work hours use half-up rounding to two decimal places.
- Regularization records preserve the actor, reason, timestamp, and field changes.
- Environment variables supply database configuration; secrets and local environment files must not be committed.
