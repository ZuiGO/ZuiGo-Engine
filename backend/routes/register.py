from fastapi import APIRouter, HTTPException
from typing import Optional
from pydantic import BaseModel
import datetime

from backend.services.register_service import get_register_state

router = APIRouter(prefix="/api/sites", tags=["register"])

@router.get("/{site_id}/register")
async def get_register(site_id: str, periodKey: Optional[str] = None):
    if not periodKey:
        # Default to current month e.g., '2026-10'
        now = datetime.datetime.now()
        periodKey = f"{now.year}-{now.month:02d}"
        
    return await get_register_state(site_id, periodKey)

class TaskConfigUpdate(BaseModel):
    enabled: bool
    disabledReason: Optional[str] = None

@router.patch("/{site_id}/tasks/{task_id}/config")
async def update_task_config(site_id: str, task_id: str, config: TaskConfigUpdate):
    if not config.enabled and not config.disabledReason:
        raise HTTPException(status_code=400, detail="Disabling a task requires a reason.")
    
    from backend.db.mongo import get_db
    db = get_db()
    
    update_doc = {
        "enabled": config.enabled,
        "disabledReason": config.disabledReason if not config.enabled else None,
        "updatedAt": datetime.datetime.utcnow().isoformat()
    }
    
    await db.site_task_configs.update_one(
        {"siteId": site_id, "taskId": task_id},
        {"$set": update_doc},
        upsert=True
    )
    
    return {"status": "success", "message": f"Config updated for {task_id}"}

@router.get("/{site_id}/reports/cadence/{cadence}")
async def get_cadence_report(site_id: str, cadence: str, periodKey: Optional[str] = None, pdf: Optional[str] = None):
    from fastapi.responses import HTMLResponse, Response
    from backend.services.cadence_reports import generate_cadence_report_html
    from backend.routes.reports import _render_pdf
    
    if cadence not in ["weekly", "monthly", "quarterly"]:
        raise HTTPException(status_code=400, detail="Invalid cadence")
        
    if not periodKey:
        now = datetime.datetime.now()
        periodKey = f"{now.year}-{now.month:02d}"
        
    html = await generate_cadence_report_html(site_id, cadence, periodKey)
    
    if pdf == "1":
        pdf_bytes = await _render_pdf(html)
        if not pdf_bytes:
            raise HTTPException(status_code=500, detail="Failed to generate PDF")
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{cadence}-report-{site_id}.pdf"'}
        )
        
    return HTMLResponse(html)
