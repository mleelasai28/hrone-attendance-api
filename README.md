# Employee Attendance & Analytics API

A REST API built with FastAPI and MongoDB for employee management, attendance tracking, attendance regularization, and analytics.

## Features

- Employee creation and listing
- Attendance punch-in and punch-out
- Attendance filtering and pagination
- Attendance regularization with audit history
- Monthly employee attendance analytics
- Department summary and daily trend analytics
- Late-arrival leaderboard
- MongoDB query-plan inspection using execution statistics

## Tech Stack

- Python 3.11+
- FastAPI
- MongoDB
- PyMongo
- Pydantic

## Requirements

- Python 3.11 or later
- MongoDB running locally or on an accessible server
- pip

## Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/mleelasai28/hrone-attendance-api.git
   cd hrone-attendance-api
   ```

2. Create and activate a virtual environment.

   Windows PowerShell:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Configure the MongoDB connection using environment variables if required.

5. Start the API:

   ```bash
   py -m uvicorn app.main:app --reload --port 8000
   ```

6. Open the interactive API documentation:

   http://127.0.0.1:8000/docs

## Configuration

- `MONGO_URI`: MongoDB connection URI.
- `MONGO_DB`: MongoDB database name. The default is `attendance_db`.

Do not commit `.env` files, credentials, or other secrets.

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/employees` | Create an employee |
| GET | `/employees` | List employees |
| POST | `/attendance/punch-in` | Record punch-in |
| POST | `/attendance/punch-out` | Record punch-out |
| GET | `/attendance` | List attendance records |
| PATCH | `/attendance/{emp_code}/{date}` | Regularize attendance |
| GET | `/analytics/employees/{emp_code}/monthly` | Employee monthly analytics |
| GET | `/analytics/departments/summary` | Department summary |
| GET | `/analytics/leaderboard/late` | Late-arrival leaderboard |
| GET | `/analytics/departments/{department}/trend` | Daily department trend |
| GET | `/admin/explain/{endpoint}` | Inspect MongoDB query execution |

## Testing

Use `/docs` to exercise endpoints and inspect response codes and response bodies. The project was syntax-checked and selected endpoints/query plans were smoke-tested during development; the full assignment edge-case suite and a 100k-record performance test have not been run.

## Verification Performed

- The Python syntax check completed successfully.
- The `department_trend` explain endpoint was tested with a date range.
- The explain response reported `uses_ixscan: true` and `uses_collscan: false` for that test.
- The latest code changes were committed and pushed to the `main` branch.

Other endpoint checks should be considered complete only after their corresponding tests have been run successfully.

## Remaining Checks

- Invalid timestamp and request-body validation
- Overnight-shift attendance-date behavior
- Late-arrival and overtime boundary conditions
- Leaderboard tie handling and department filtering
- Pagination limits and filter combinations
- Database index creation and uniqueness constraints
- All five explain endpoint variants and their response contracts
- Installation and startup from a clean environment

## Security

Never commit database credentials, API secrets, or local environment files to the repository.
