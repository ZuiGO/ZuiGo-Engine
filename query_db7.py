import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    db = AsyncIOMotorClient('mongodb://localhost:27017')['rankengine']
    job = await db.analysis_jobs.find_one({'url': {'$regex': 'fluidcontrols', '$options': 'i'}}, sort=[('created_at', -1)])
    if job:
        targets = await db.user_flows.distinct("target_url", {"job_id": job['_id']})
        print("Distinct targets:", len(targets))
    else:
        print("Not found")

asyncio.run(main())
