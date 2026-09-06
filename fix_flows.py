import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    db = AsyncIOMotorClient('mongodb://localhost:27017')['rankengine']
    async for job in db.analysis_jobs.find({"status": "completed"}):
        targets = await db.user_flows.distinct("target_url", {"job_id": job['_id']})
        target_count = len(targets)
        
        # update summary.total_user_flows
        await db.analysis_jobs.update_one(
            {"_id": job['_id']},
            {"$set": {"summary.total_user_flows": target_count}}
        )
        print(f"Updated job {job['_id']} to {target_count} flows")

asyncio.run(main())
