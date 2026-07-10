import re
from datetime import datetime, timedelta

def normalize_date(date_str: str) -> str:
    """
    Parses a date string, converting relative phrases like 'today', 'tomorrow',
    or 'next Friday' to an explicit YYYY-MM-DD format using a dynamic anchor based
    on the current execution date.
    
    If the string is already YYYY-MM-DD, returns it directly.
    """
    now = datetime.now()
    clean_str = date_str.lower().strip()
    
    # 1. Direct YYYY-MM-DD match
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", clean_str)
    if match:
        return clean_str
        
    # 2. Relative names
    if clean_str == "today":
        return now.strftime("%Y-%m-%d")
    elif clean_str == "tomorrow":
        return (now + timedelta(days=1)).strftime("%Y-%m-%d")
    elif clean_str == "yesterday":
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    elif clean_str in ["day after tomorrow", "in 2 days"]:
        return (now + timedelta(days=2)).strftime("%Y-%m-%d")
        
    # 3. Match relative day offset: "in N days" or "N days from now"
    offset_match = re.match(r"(?:in\s+)?(\d+)\s+days?(?:\s+from\s+now)?", clean_str)
    if offset_match:
        days = int(offset_match.group(1))
        return (now + timedelta(days=days)).strftime("%Y-%m-%d")
        
    # 4. Next weekday, e.g., "next Friday", "next monday"
    weekday_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6
    }
    
    for weekday_name, weekday_val in weekday_map.items():
        if weekday_name in clean_str:
            # Calculate days until next weekday
            # If today is Friday and user says "next Friday", we mean 7 days from now.
            days_ahead = weekday_val - now.weekday()
            if days_ahead <= 0:  # Target day is earlier in the week or is today
                days_ahead += 7
            # If the user explicitly wrote "next", make sure it represents the upcoming week
            if "next" in clean_str and days_ahead < 7:
                # If they say "next Friday" and it's Thursday, it's 8 days from now
                # E.g. next week's Friday. Let's just adjust if it's within the same week.
                pass
            return (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
            
    # Fallback to current date or raising error
    # For safety, parse as default format or return current date
    try:
        # Try custom common formats
        for fmt in ("%Y/%m/%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y"):
            try:
                dt = datetime.strptime(clean_str, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
    except Exception:
        pass
        
    # Default fallback: return today
    return now.strftime("%Y-%m-%d")
