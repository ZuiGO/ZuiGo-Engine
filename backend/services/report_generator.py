import os
from datetime import datetime
from backend.db.mongo import get_db

async def generate_monthly_report_html(job_id: str) -> str:
    db = get_db()
    job = await db.analysis_jobs.find_one({"_id": job_id})
    if not job:
        return {"error": "Job not found"}
        
    summary = job.get("summary", {})
    url = job.get("url", "")
    
    # Calculate some dynamic values
    broken_links = summary.get("broken_link_count", 0)
    broken_status = "ok" if broken_links == 0 else ("gap" if broken_links > 50 else "part")
    broken_label = "OK" if broken_links == 0 else "Needs Work"
    
    ai_vis = summary.get("ai_visibility", {})
    local_seo = summary.get("local_seo", {})
    pseo = summary.get("programmatic_seo", {})
    
    # Context dictionary for string formatting
    ctx = {
        "target_url": url,
        "date": datetime.utcnow().strftime("%d %b %Y"),
        "health_grade": summary.get("health_grade", "N/A"),
        "total_pages": summary.get("total_pages", 0),
        "smart_keywords": summary.get("total_smart_keywords", 0),
        "broken_links": broken_links,
        "broken_status": broken_status,
        "broken_label": broken_label,
        "ai_score": ai_vis.get("score", 0) if isinstance(ai_vis, dict) else 0,
        "total_links_scanned": summary.get("total_links_scanned", 0),
        "canonical_issues": summary.get("canonical_issues", 0),
        "duplicate_pages": summary.get("duplicate_pages", 0),
        "cwv_pages": summary.get("cwv_pages", 0),
        "structured_data_valid": summary.get("structured_data_valid", 0),
        "local_schema": "Yes" if local_seo.get("local_business_schema") else "No",
        "llms_txt": "Yes" if ai_vis.get("llms_txt_present") else "No",
        "total_vectors": summary.get("total_vectors", 0),
        "programmatic_score": pseo.get("score", 0) if isinstance(pseo, dict) else 0,
        "clusters": pseo.get("clusters", 0) if isinstance(pseo, dict) else 0,
        "total_content_items": summary.get("total_content_items", 0),
        "local_score": local_seo.get("score", 0) if isinstance(local_seo, dict) else 0,
        "contact_page": "Yes" if local_seo.get("contact_page_present") else "No",
        "nap_schema": "Yes" if local_seo.get("nap_schema_present") else "No",
        "total_external_links": summary.get("total_external_links", 0),
        "total_backlinks": summary.get("total_backlinks", 0)
    }
    
    template_path = os.path.join(os.path.dirname(__file__), "..", "templates", "monthly_report.html")
    with open(template_path, "r") as f:
        html_template = f.read()
        
    return html_template.format(**ctx)
