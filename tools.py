import os
import sqlite3
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any
from langchain_core.tools import tool

DB_PATH = os.path.join(os.path.dirname(__file__), "scheduler.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS busy_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            participant TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            email TEXT NOT NULL,
            details TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

@tool
def check_availability(date: str) -> List[Dict[str, Any]]:
    """
    Check booked time slots for a given date (YYYY-MM-DD).
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT participant, start_time, end_time FROM busy_slots WHERE start_time LIKE ?",
        (f"{date}%",)
    )
    rows = cur.fetchall()
    conn.close()
    return [
        {"participant": r[0], "start_time": r[1], "end_time": r[2]}
        for r in rows
    ]

@tool
def reserve_slot(date: str, time: str, email: str, duration_minutes: int = 60) -> Dict[str, Any]:
    """
    Reserve an appointment slot for a participant.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    try:
        start_dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    except ValueError:
        conn.close()
        return {"success": False, "message": f"Invalid date/time format: {date} {time}."}

    end_dt = start_dt + timedelta(minutes=duration_minutes)
    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M")
    end_iso = end_dt.strftime("%Y-%m-%dT%H:%M")

    cur.execute("""
        SELECT COUNT(*) FROM busy_slots
        WHERE participant = ? AND start_time < ? AND end_time > ?
    """, (email, end_iso, start_iso))
    
    if cur.fetchone()[0] > 0:
        conn.close()
        return {"success": False, "message": "Time slot is already occupied."}

    cur.execute(
        "SELECT COUNT(*) FROM reservations WHERE date = ? AND time = ? AND email = ?",
        (date, time, email)
    )
    if cur.fetchone()[0] > 0:
        conn.close()
        return {"success": False, "message": "Reservation already exists."}

    cur.execute(
        "INSERT INTO reservations (date, time, email, details) VALUES (?, ?, ?, ?)",
        (date, time, email, f"Booked ({duration_minutes} mins)")
    )
    cur.execute(
        "INSERT INTO busy_slots (participant, start_time, end_time) VALUES (?, ?, ?)",
        (email, start_iso, end_iso)
    )
    conn.commit()
    conn.close()

    return {"success": True, "message": f"Reserved successfully."}

@tool
def send_booking_notification(email: str, details: str) -> Dict[str, Any]:
    """
    Send booking confirmation payload via webhook POST.
    """
    webhook_url = os.environ.get("WEBHOOK_URL", "https://httpbin.org/post")
    payload = {
        "event": "booking_confirmed",
        "recipient": email,
        "details": details,
        "timestamp": datetime.now().isoformat()
    }
    try:
        resp = requests.post(webhook_url, json=payload, timeout=8)
        return {
            "success": resp.ok,
            "status_code": resp.status_code,
            "message": "Notification dispatched." if resp.ok else f"Webhook returned {resp.status_code}."
        }
    except Exception as e:
        return {"success": False, "status_code": 0, "message": str(e)}

@tool
def cancel_slot(date: str, time: str, email: str) -> Dict[str, Any]:
    """
    Cancel an existing appointment slot for a participant.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.execute(
        "SELECT COUNT(*) FROM reservations WHERE date = ? AND time = ? AND email = ?",
        (date, time, email)
    )
    if cur.fetchone()[0] == 0:
        conn.close()
        return {"success": False, "message": "Reservation not found."}
        
    cur.execute(
        "DELETE FROM reservations WHERE date = ? AND time = ? AND email = ?",
        (date, time, email)
    )
    
    try:
        start_dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        start_iso = start_dt.strftime("%Y-%m-%dT%H:%M")
        cur.execute(
            "DELETE FROM busy_slots WHERE participant = ? AND start_time = ?",
            (email, start_iso)
        )
    except Exception:
        pass
        
    conn.commit()
    conn.close()
    return {"success": True, "message": "Cancelled successfully."}

@tool
def reschedule_slot(email: str, old_date: str, old_time: str, new_date: str, new_time: str, duration_minutes: int = 60) -> Dict[str, Any]:
    """
    Reschedule an existing appointment to a new date and time.
    """
    cancel_res = cancel_slot.invoke({"date": old_date, "time": old_time, "email": email})
    if not cancel_res["success"]:
        return {"success": False, "message": f"Failed to cancel old slot: {cancel_res['message']}"}
        
    reserve_res = reserve_slot.invoke({"date": new_date, "time": new_time, "email": email, "duration_minutes": duration_minutes})
    if not reserve_res["success"]:
        # Rollback cancellation by re-reserving old slot
        reserve_slot.invoke({"date": old_date, "time": old_time, "email": email, "duration_minutes": duration_minutes})
        return {"success": False, "message": f"Failed to reserve new slot: {reserve_res['message']}. Original slot kept."}
        
    return {"success": True, "message": "Rescheduled successfully."}

TOOLS = [check_availability, reserve_slot, send_booking_notification, cancel_slot, reschedule_slot]
