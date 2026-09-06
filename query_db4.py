import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    db = AsyncIOMotorClient('mongodb://localhost:27017')['rankengine']
    job = await db.analysis_jobs.find_one({'url': {'$regex': 'fluidcontrols', '$options': 'i'}}, sort=[('created_at', -1)])
    if job:
        pages = await db.pages.find({'job_id': job['_id'], 'page_type': 'home'}).to_list(length=5)
        for p in pages:
            print(f"URL: {p['url']}, Path: '{p['url'].split(' fluidcontrols.com')[-1]}', Type: {p['page_type']}")
    else:
        print("Not found")

asyncio.run(main())
