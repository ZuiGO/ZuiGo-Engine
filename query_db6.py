import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    db = AsyncIOMotorClient('mongodb://localhost:27017')['rankengine']
    job = await db.analysis_jobs.find_one({'url': {'$regex': 'fluidcontrols', '$options': 'i'}}, sort=[('created_at', -1)])
    if job:
        pipeline = [
            {"$match": {"job_id": job['_id']}},
            {"$group": {"_id": "$target_url"}}
        ]
        targets = await db.user_flows.aggregate(pipeline).to_list(length=None)
        print("Unique targets:", len(targets))
    else:
        print("Not found")

asyncio.run(main())
