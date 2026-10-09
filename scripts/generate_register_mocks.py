import asyncio
import argparse
import random
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

from backend.db.mongo import connect_db, get_db, close_db
from backend.config import settings
from backend.models.register_schemas import RunStatus, TaskTrigger, Mode
from backend.services.register_service import get_all_task_defs

async def generate_mocks(site_id: str):
    await connect_db(settings.mongodb_uri)
    db = get_db()
    
    # Clear existing mock runs for this site
    await db.task_runs.delete_many({"siteId": site_id})
    print(f"Cleared existing task runs for site {site_id}")
    
    task_defs = get_all_task_defs()
    now = datetime.now()
    
    runs_to_insert = []
    
    # Generate for the past 6 months
    for month_offset in range(6, 0, -1):
        target_date = now - relativedelta(months=month_offset)
        
        # Determine period key based on cadence
        for task in task_defs:
            if task.cadence == "weekly":
                # Generate 4 weeks per month for simplicity
                for week in range(1, 5):
                    week_date = target_date.replace(day=1) + timedelta(days=(week-1)*7)
                    period_key = f"{week_date.year}-W{week_date.isocalendar()[1]:02d}"
                    runs_to_insert.append(create_mock_run(site_id, task, period_key, week_date))
                    
            elif task.cadence == "monthly":
                period_key = f"{target_date.year}-{target_date.month:02d}"
                runs_to_insert.append(create_mock_run(site_id, task, period_key, target_date))
                
            elif task.cadence == "quarterly":
                # Only insert if this month is the end of a quarter
                if target_date.month in [3, 6, 9, 12]:
                    quarter = (target_date.month - 1) // 3 + 1
                    period_key = f"{target_date.year}-Q{quarter}"
                    runs_to_insert.append(create_mock_run(site_id, task, period_key, target_date))
                    
    if runs_to_insert:
        await db.task_runs.insert_many(runs_to_insert)
        print(f"Inserted {len(runs_to_insert)} mock runs for site {site_id}")
    
    await close_db()

def create_mock_run(site_id, task, period_key, date):
    # Determine status based on mode
    status = RunStatus.done
    skip_reason = None
    
    if task.mode == Mode.auto:
        status = RunStatus.done  # Auto tasks always done
    elif task.mode == Mode.assisted:
        # Assisted tasks mostly done, sometimes blocked/skipped
        roll = random.random()
        if roll < 0.1:
            status = RunStatus.skipped
            skip_reason = "Blocked by engineering"
        elif roll < 0.15:
            status = RunStatus.failed
            skip_reason = "API failure"
    elif task.mode == Mode.manual:
        # Manual tasks mostly missed
        roll = random.random()
        if roll < 0.6:
            status = RunStatus.skipped
            skip_reason = "Resourced diverted"
        elif roll < 0.8:
            status = RunStatus.skipped
            skip_reason = "Client pending"
            
    return {
        "id": f"mock-{task.id}-{period_key}",
        "siteId": site_id,
        "taskId": task.id,
        "periodKey": period_key,
        "status": status.value,
        "startedAt": date.isoformat(),
        "finishedAt": (date + timedelta(hours=1)).isoformat(),
        "triggeredBy": TaskTrigger.schedule.value,
        "skipReason": skip_reason,
        "evidence": [],
        "metrics": [],
        "notes": "Mock generated run"
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("site_id", help="Site ID to generate mocks for")
    args = parser.parse_args()
    
    asyncio.run(generate_mocks(args.site_id))
