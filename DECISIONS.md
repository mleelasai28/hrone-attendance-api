
# Technical Decisions

## Framework and Database

- FastAPI is used to expose REST endpoints and generate interactive API documentation.
- MongoDB is used to store employee and attendance records.
- PyMongo is used for database access and aggregation pipelines.

## Attendance Dates and Timestamps

- API timestamps are represented as epoch milliseconds.
- MongoDB stores timestamp values as BSON datetimes.
- Attendance dates use the Asia/Kolkata calendar.
- Overnight shifts require attendance-date handling across midnight.

## Attendance Calculations

- Late arrivals are evaluated against the employee's configured shift start.
- Overtime is calculated relative to the configured shift end.
- Half-day classification is based on calculated work hours.
- Working-day analytics use Monday through Friday.

## Regularization and Audit History

- Attendance corrections are performed through the PATCH endpoint.
- Regularization history records the actor, reason, timestamp, and field changes.

## Analytics and Query Performance

- MongoDB aggregation pipelines are used for analytics.
- The department trend uses `$densify` to generate a daily date series.
- Compound indexes support common attendance queries.
- The admin explain endpoint exposes query-plan information to verify index usage.

## Configuration and Security

- MongoDB connection settings can be supplied through environment variables.
- Secrets and local environment files must not be committed to Git.
