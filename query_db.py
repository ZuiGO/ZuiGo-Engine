import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    db = AsyncIOMotorClient('mongodb://localhost:27017')['rankengine']
    # Use regex to find any job containing fluidcontrols
    job = await db.analysis_jobs.find_one({'url': {'$regex': 'fluidcontrols', '$options': 'i'}}, sort=[('created_at', -1)])
    if job:
        print("Job ID:", job['_id'])
        print("URL:", job['url'])
        print("User flows in summary:", job.get('summary', {}).get('total_user_flows', 'N/A'))
        
        pages = await db.pages.find({'job_id': job['_id']}).to_list(length=1000)
        types = {}
        for p in pages:
            pt = p.get('page_type')
            types[pt] = types.get(pt, 0) + 1
        print("Page types:", types)
    else:
        print("Not found")

asyncio.run(main())
