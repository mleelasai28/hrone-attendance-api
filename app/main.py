import os
import re
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, StrictInt, field_validator, model_validator
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
from bson import ObjectId

load_dotenv()

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

app = FastAPI(
    title="Employee Attendance & Analytics API",
    version="2.0.0",
)


# ----------------------------- Helpers ---------------------------------

def now_ist():
    return datetime.now(IST).replace(microsecond=0)


def timestamp_to_datetime(value):
    if type(value) is not int or not 100000000000 <= value <= 4102444800000:
        raise HTTPException(422, "Timestamp must be epoch milliseconds")
    return datetime.fromtimestamp(value / 1000, tz=UTC).replace(microsecond=0)


def datetime_to_ms(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp() * 1000)


def mongo_datetime(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0)


def parse_date(value):
    try:
        parsed = date.fromisoformat(value)
        if len(value) != 10:
            raise ValueError
        return parsed
    except (ValueError, TypeError):
        raise HTTPException(422, "Date must use YYYY-MM-DD format")


def validate_month(month):
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month or ""):
        raise HTTPException(422, "month must use YYYY-MM format")
    return int(month[:4]), int(month[5:])


def month_bounds(month):
    year, number = validate_month(month)
    last_day = monthrange(year, number)[1]
    return f"{month}-01", f"{month}-{last_day:02d}"


def round_half_up(value, places=2):
    quantum = Decimal("1").scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def shift_datetime(attendance_date, shift_time):
    hour, minute = map(int, shift_time.split(":"))
    return datetime.combine(
        date.fromisoformat(attendance_date),
        datetime.min.time().replace(hour=hour, minute=minute),
    ).replace(tzinfo=IST)


def attendance_date_for(punch_in, emp):
    local_time = punch_in.astimezone(IST)
    shift_end_hour, shift_end_minute = map(int, emp["shift_end"].split(":"))
    shift_end_minutes = shift_end_hour * 60 + shift_end_minute
    local_minutes = local_time.hour * 60 + local_time.minute

    if emp["shift_end"] <= emp["shift_start"] and local_minutes < shift_end_minutes:
        return (local_time.date() - timedelta(days=1)).isoformat()

    return local_time.date().isoformat()


def compute_late_minutes(punch_in, shift_start, attendance_date):
    start = shift_datetime(attendance_date, shift_start)
    local_in = punch_in.astimezone(IST)

    if start > local_in:
        start -= timedelta(days=1)

    minutes = int((local_in - start).total_seconds() // 60)
    return minutes if minutes > 10 else 0


def compute_work_hours(punch_in, punch_out):
    hours = (punch_out - punch_in).total_seconds() / 3600
    return round_half_up(hours, 2)


def compute_overtime(punch_out, shift_end, attendance_date, punch_in):
    end = shift_datetime(attendance_date, shift_end)

    if end <= punch_in.astimezone(IST):
        end += timedelta(days=1)

    minutes = max(0, int((punch_out.astimezone(IST) - end).total_seconds() // 60))
    return minutes if minutes >= 30 else 0


def serialize_attendance(doc):
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    for key in ("punch_in", "punch_out"):
        doc[key] = datetime_to_ms(doc.get(key))

    for entry in doc.get("history", []):
        entry["at"] = datetime_to_ms(entry.get("at"))
        for change in entry.get("changes", {}).values():
            for key in ("from", "to"):
                if isinstance(change.get(key), datetime):
                    change[key] = datetime_to_ms(change[key])

    return doc


def validate_pagination(page, page_size):
    if page < 1 or not 1 <= page_size <= 100:
        raise HTTPException(422, "page must be >= 1 and page_size must be between 1 and 100")


def presence_status(status):
    return status in ("PRESENT", "WFH", "ON_DUTY")


@app.on_event("startup")
def create_indexes():
    db.employees.create_index([("emp_code", ASCENDING)], unique=True)
    db.employees.create_index([("department", ASCENDING), ("joined_on", ASCENDING)])
    db.attendance_logs.create_index(
        [("emp_code", ASCENDING), ("date", ASCENDING)],
        unique=True,
    )
    db.attendance_logs.create_index(
        [("date", ASCENDING), ("status", ASCENDING)]
    )


# ----------------------------- Models ----------------------------------

class EmployeeIn(BaseModel):
    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    department: str = Field(min_length=1, max_length=100)
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Invalid email address")
        return value

    @field_validator("shift_start", "shift_end")
    @classmethod
    def validate_shift(cls, value):
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("Shift time must use HH:MM format")
        return value

    @field_validator("joined_on")
    @classmethod
    def validate_joined_on(cls, value):
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError
        except ValueError:
            raise ValueError("joined_on must use YYYY-MM-DD format")
        return value

    @model_validator(mode="after")
    def validate_shift_range(self):
        if self.shift_start == self.shift_end:
            raise ValueError("shift_start and shift_end must differ")
        return self


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[StrictInt] = None
    status: str = "PRESENT"

    @field_validator("punched_at")
    @classmethod
    def validate_timestamp(cls, value):
        if value is not None:
            timestamp_to_datetime(value)
        return value


class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[StrictInt] = None

    @field_validator("punched_at")
    @classmethod
    def validate_timestamp(cls, value):
        if value is not None:
            timestamp_to_datetime(value)
        return value


class AttendanceUpdateIn(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[StrictInt] = None
    punch_out: Optional[StrictInt] = None
    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)

    @field_validator("punch_in", "punch_out")
    @classmethod
    def validate_timestamps(cls, value):
        if value is not None:
            timestamp_to_datetime(value)
        return value


# ----------------------------- Health ----------------------------------

@app.get("/health")
def health():
    try:
        db.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(503, "Database unavailable")


# ----------------------------- Employees -------------------------------

@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    doc["created_at"] = datetime.now(UTC).replace(microsecond=0)

    try:
        result = db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "emp_code already exists")

    doc.pop("_id", None)
    doc["created_at"] = datetime_to_ms(doc["created_at"])
    return doc


@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    query = {}
    if department is not None:
        query["department"] = department

    total = db.employees.count_documents(query)
    items = list(
        db.employees.find(query, {"_id": 0})
        .sort("emp_code", ASCENDING)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )

    for item in items:
        item["created_at"] = datetime_to_ms(item.get("created_at"))

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ----------------------------- Punch In --------------------------------

@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if emp is None:
        raise HTTPException(404, "Employee not found")

    if body.status not in ("PRESENT", "WFH", "ON_DUTY"):
        raise HTTPException(422, "Invalid attendance status for punch-in")

    punched_at = timestamp_to_datetime(body.punched_at) if body.punched_at is not None else datetime.now(UTC).replace(microsecond=0)
    local_in = punched_at.astimezone(IST)
    attendance_date = attendance_date_for(punched_at, emp)


    print("DEBUG punch-in UTC:", punched_at)
    print("DEBUG punch-in IST:", local_in)
    print("DEBUG calculated attendance date:", attendance_date)
    print("DEBUG employee shift:", emp["shift_start"], emp["shift_end"])

    doc = {
        "emp_code": body.emp_code,
        "date": attendance_date,
        "status": body.status,
        "punch_in": punched_at,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(punched_at, emp["shift_start"], attendance_date),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }

    try:
        result = db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "Already punched in for this attendance date")

    doc["_id"] = result.inserted_id
    return serialize_attendance(doc)


# ----------------------------- Punch Out -------------------------------



@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    punched_at = (
        timestamp_to_datetime(body.punched_at)
        if body.punched_at is not None
        else datetime.now(UTC).replace(microsecond=0)
    )

    attendance_date = attendance_date_for(punched_at, emp)

    print("DEBUG punch-out date:", attendance_date)
    print("DEBUG employee:", body.emp_code)
    record = db.attendance_logs.find_one({
        "emp_code": body.emp_code,
        "date": attendance_date,
    })
    print("DEBUG first lookup:", record)
    # For overnight shifts, check the previous attendance date too.
    if record is None:
        previous_date = (
            date.fromisoformat(attendance_date) - timedelta(days=1)
        ).isoformat()

        record = db.attendance_logs.find_one({
            "emp_code": body.emp_code,
            "date": previous_date,
        })

        if record is not None:
            attendance_date = previous_date

    if record is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "Punch-in record not found",
                "searched_date": attendance_date,
            },
        )

    if record.get("punch_out") is not None:
        raise HTTPException(status_code=409, detail="Already punched out")

    punch_in_time = mongo_datetime(record["punch_in"])

    if punched_at <= punch_in_time:
        raise HTTPException(
            status_code=422,
            detail="Punch-out must be after punch-in",
        )

    hours = compute_work_hours(punch_in_time, punched_at)
    overtime = compute_overtime(
        punched_at,
        emp["shift_end"],
        attendance_date,
        punch_in_time,
    )

    result = db.attendance_logs.update_one(
        {"_id": record["_id"], "punch_out": None},
        {
            "$set": {
                "punch_out": punched_at,
                "work_hours": hours,
                "overtime_minutes": overtime,
                "half_day": hours < 4.5,
            }
        },
    )

    if result.modified_count != 1:
        raise HTTPException(
            status_code=409,
            detail="Attendance record changed; retry",
        )

    updated = db.attendance_logs.find_one({"_id": record["_id"]})
    return serialize_attendance(updated)

# ----------------------------- Attendance List -------------------------

@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    query = {}
    if emp_code:
        query["emp_code"] = emp_code
    if status:
        query["status"] = status

    if date_from:
        parse_date(date_from)
        query.setdefault("date", {})["$gte"] = date_from
    if date_to:
        parse_date(date_to)
        query.setdefault("date", {})["$lte"] = date_to
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must not be after date_to")

    total = db.attendance_logs.count_documents(query)
    docs = list(
        db.attendance_logs.find(query)
        .sort("date", DESCENDING)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "items": [serialize_attendance(doc) for doc in docs],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ----------------------------- Regularization --------------------------

@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(emp_code: str, date: str, body: AttendanceUpdateIn):
    parse_date(date)

    emp = db.employees.find_one({"emp_code": emp_code})
    if emp is None:
        raise HTTPException(404, "Employee not found")

    record = db.attendance_logs.find_one({"emp_code": emp_code, "date": date})
    if record is None:
        raise HTTPException(404, "Attendance record not found")

    updates = body.model_dump(exclude_unset=True)
    changes = {}
    final_status = updates.get("status", record["status"])
    final_in = timestamp_to_datetime(updates["punch_in"]) if updates.get("punch_in") is not None else record.get("punch_in")
    final_out = timestamp_to_datetime(updates["punch_out"]) if updates.get("punch_out") is not None else record.get("punch_out")

    if final_status not in ("PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"):
        raise HTTPException(422, "Invalid status")

    if final_status in ("ABSENT", "LEAVE"):
        if updates.get("punch_in") is not None or updates.get("punch_out") is not None:
            raise HTTPException(422, "ABSENT or LEAVE cannot include punch times")
        final_in = None
        final_out = None
    elif final_in is None:
        raise HTTPException(422, "Presence status requires punch_in")

    if final_in is not None and final_out is not None:
        if final_out <= final_in:
            raise HTTPException(422, "punch_out must be after punch_in")
        if (final_out - final_in).total_seconds() > 24 * 3600:
            raise HTTPException(422, "Punch duration cannot exceed 24 hours")
        if final_in.astimezone(IST).date().isoformat() != date:
            raise HTTPException(422, "punch_in must fall on the attendance date")

    old_values = {
        "status": record.get("status"),
        "punch_in": datetime_to_ms(record.get("punch_in")),
        "punch_out": datetime_to_ms(record.get("punch_out")),
    }
    new_values = {
        "status": final_status,
        "punch_in": datetime_to_ms(final_in),
        "punch_out": datetime_to_ms(final_out),
    }

    for key in ("status", "punch_in", "punch_out"):
        if old_values[key] != new_values[key]:
            changes[key] = {"from": old_values[key], "to": new_values[key]}

    if not changes:
        raise HTTPException(422, "No attendance fields changed")

    set_fields = {
        "status": final_status,
        "punch_in": final_in,
        "punch_out": final_out,
        "late_minutes": compute_late_minutes(final_in, emp["shift_start"], date) if final_in else 0,
    }

    if final_in is not None and final_out is not None:
        hours = compute_work_hours(final_in, final_out)
        set_fields["work_hours"] = hours
        set_fields["half_day"] = hours < 4.5
        set_fields["overtime_minutes"] = compute_overtime(final_out, emp["shift_end"], date, final_in)
    else:
        set_fields["work_hours"] = None
        set_fields["half_day"] = False
        set_fields["overtime_minutes"] = 0

    history_entry = {
        "at": datetime.now(UTC).replace(microsecond=0),
        "by": body.regularized_by,
        "reason": body.reason,
        "changes": changes,
    }

    result = db.attendance_logs.update_one(
        {"_id": record["_id"], "history": record.get("history", [])},
        {"$set": set_fields, "$push": {"history": history_entry}},
    )
    if result.modified_count != 1:
        raise HTTPException(409, "Attendance record changed; retry")

    return serialize_attendance(db.attendance_logs.find_one({"_id": record["_id"]}))


# ----------------------------- Monthly Analytics -----------------------

@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str):
    year, month_num = validate_month(month)
    emp = db.employees.find_one({"emp_code": emp_code})
    if emp is None:
        raise HTTPException(404, "Employee not found")

    month_start, month_end = month_bounds(month)
    start_date = max(date(year, month_num, 1), date.fromisoformat(emp["joined_on"]))
    end_date = date(year, month_num, monthrange(year, month_num)[1])

    working_days = 0
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            working_days += 1
        current += timedelta(days=1)

    pipeline = [
        {"$match": {"emp_code": emp_code, "date": {"$gte": month_start, "$lte": month_end}}},
        {"$addFields": {"weekday": {"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}}}},
        {"$group": {
            "_id": None,
            "present_days": {"$sum": {"$cond": [
                {"$and": [
                    {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                    {"$in": ["$weekday", [2, 3, 4, 5, 6]]},
                ]},
                {"$cond": [{"$eq": ["$half_day", True]}, 0.5, 1]},
                0,
            ]}},
            "leave_days": {"$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}},
            "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]}},
            "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
            "total_overtime_minutes": {"$sum": {"$ifNull": ["$overtime_minutes", 0]}},
        }},
    ]

    result = list(db.attendance_logs.aggregate(pipeline))
    stats = result[0] if result else {}
    present_days = float(stats.get("present_days", 0))
    attendance_pct = None
    if working_days:
        attendance_pct = round_half_up(present_days * 100 / working_days)

    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": stats.get("leave_days", 0),
        "late_count": stats.get("late_count", 0),
        "total_late_minutes": stats.get("total_late_minutes", 0),
        "total_overtime_minutes": stats.get("total_overtime_minutes", 0),
        "attendance_pct": attendance_pct,
    }


# ----------------------------- Department Summary ----------------------

@app.get("/analytics/departments/summary")
def department_summary(month: str, department: Optional[str] = None):
    _, _ = validate_month(month)
    month_start, month_end = month_bounds(month)

    employee_match = {"joined_on": {"$lte": month_end}}
    if department is not None:
        employee_match["department"] = department

    employees = list(db.employees.aggregate([
        {"$match": employee_match},
        {"$group": {"_id": "$department", "headcount": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]))

    attendance_pipeline = [
        {"$match": {"date": {"$gte": month_start, "$lte": month_end}}},
        {"$lookup": {
            "from": "employees",
            "localField": "emp_code",
            "foreignField": "emp_code",
            "as": "employee",
        }},
        {"$unwind": "$employee"},
        {"$match": {"employee.joined_on": {"$lte": month_end}}},
    ]

    if department is not None:
        attendance_pipeline.append({"$match": {"employee.department": department}})

    attendance_pipeline.append({"$group": {
        "_id": "$employee.department",
        "present_days": {"$sum": {"$cond": [
            {"$and": [
                {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                {"$in": [{"$dayOfWeek": {"$dateFromString": {"dateString": "$date"}}}, [2, 3, 4, 5, 6]]},
            ]},
            {"$cond": [{"$eq": ["$half_day", True]}, 0.5, 1]},
            0,
        ]}},
        "avg_work_hours": {"$avg": {"$cond": [
            {"$and": [
                {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                {"$ne": ["$work_hours", None]},
            ]},
            "$work_hours",
            None,
        ]}},
        "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]}},
        "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
        "leave_count": {"$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}},
        "on_duty_count": {"$sum": {"$cond": [{"$eq": ["$status", "ON_DUTY"]}, 1, 0]}},
    }})

    stats = {item["_id"]: item for item in db.attendance_logs.aggregate(attendance_pipeline)}
    response = []

    for employee in employees:
        dept = employee["_id"]
        values = stats.get(dept, {})
        response.append({
            "department": dept,
            "headcount": employee["headcount"],
            "present_days": values.get("present_days", 0),
            "avg_work_hours": values.get("avg_work_hours"),
            "late_count": values.get("late_count", 0),
            "total_late_minutes": values.get("total_late_minutes", 0),
            "leave_count": values.get("leave_count", 0),
            "on_duty_count": values.get("on_duty_count", 0),
        })

    return response


# ----------------------------- Late Leaderboard ------------------------

@app.get("/analytics/leaderboard/late")
def late_leaderboard(month: str, limit: int = Query(10, ge=1, le=100)):
    _, _ = validate_month(month)
    month_start, month_end = month_bounds(month)

    pipeline = [
        {"$match": {
            "date": {"$gte": month_start, "$lte": month_end},
            "late_minutes": {"$gt": 0},
        }},
        {"$group": {
            "_id": "$emp_code",
            "late_count": {"$sum": 1},
            "total_late_minutes": {"$sum": "$late_minutes"},
        }},
        {"$sort": {"total_late_minutes": -1, "_id": 1}},
        {"$limit": limit},
        {"$lookup": {
            "from": "employees",
            "localField": "_id",
            "foreignField": "emp_code",
            "as": "employee",
        }},
        {"$unwind": {"path": "$employee", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "_id": 0,
            "emp_code": "$_id",
            "name": "$employee.name",
            "department": "$employee.department",
            "late_count": 1,
            "total_late_minutes": 1,
        }},
    ]

    return {"month": month, "items": list(db.attendance_logs.aggregate(pipeline))}


# ----------------------------- Department Trend ------------------------

@app.get("/analytics/departments/{department}/trend")

def department_trend(department: str, month: str):
    year, month_num = validate_month(month)
    month_start, month_end = month_bounds(month)

    
    start = datetime(year, month_num, 1, tzinfo=UTC)
    end = start + timedelta(days=monthrange(year, month_num)[1])


    pipeline = [
        {
            "$match": {
                "date": {"$gte": month_start, "$lte": month_end}
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "emp_code",
                "foreignField": "emp_code",
                "as": "employee",
            }
        },
        {"$unwind": "$employee"},
        {"$match": {"employee.department": department}},
        {
            "$addFields": {
                "day_date": {
                    "$dateFromString": {"dateString": "$date"}
                }
            }
        },
        {
            "$addFields": {
                "weekday": {"$dayOfWeek": "$day_date"}
            }
        },
        {
            "$group": {
                "_id": "$day_date",
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$gte": ["$weekday", 2]},
                                    {"$lte": ["$weekday", 6]},
                                    {
                                        "$in": [
                                            "$status",
                                            ["PRESENT", "WFH", "ON_DUTY"],
                                        ]
                                    },
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$half_day", True]},
                                    0.5,
                                    1,
                                ]
                            },
                            0,
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$gte": ["$weekday", 2]},
                                    {"$lte": ["$weekday", 6]},
                                    {
                                        "$gt": [
                                            {"$ifNull": ["$late_minutes", 0]},
                                            0,
                                        ]
                                    },
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
            }
        },
        {
            "$densify": {
                "field": "_id",
                "range": {
                    "step": 1,
                    "unit": "day",
                    "bounds": [start, end],
                },
            }
        },
        {
            "$project": {
                "_id": 0,
                "date": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$_id",
                    }
                },
                "present_days": {"$ifNull": ["$present_days", 0]},
                "late_count": {"$ifNull": ["$late_count", 0]},
            }
        },
        {"$sort": {"date": 1}},
    ]

    return {
        "department": department,
        "month": month,
        "items": list(db.attendance_logs.aggregate(pipeline)),
    }


# ----------------------------- Query Explain ---------------------------

@app.get("/admin/explain/{endpoint}")
def explain_endpoint(endpoint: str):
    if endpoint == "employees":
        command = {
            "find": "employees",
            "filter": {"emp_code": {"$gte": "EMP0000", "$lte": "EMP999999"}},
            "sort": {"emp_code": 1},
        }
    elif endpoint == "attendance":
        command = {
            "find": "attendance_logs",
            "filter": {
                "emp_code": "EMP1001",
                "date": {"$gte": "2026-01-01", "$lte": "2026-12-31"},
            },
            "sort": {"date": 1},
        }
    else:
        raise HTTPException(422, "endpoint must be employees or attendance")

    plan = db.command("explain", command, verbosity="queryPlanner")
    text_plan = str(plan)

    return {
        "endpoint": endpoint,
        "plan": plan,
        "uses_ixscan": "IXSCAN" in text_plan,
        "uses_collscan": "COLLSCAN" in text_plan,
    }