import html as _html_esc
from datetime import datetime
from backend.services.register_service import get_register_state, get_all_task_defs

_REPORT_CSS = """
@page { size: A4; margin: 14mm; }
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  color: #1e293b; font-size: 13px; line-height: 1.55; margin: 0; padding: 20px;}
.cover { background: linear-gradient(135deg, #0f172a, #1e293b 60%, #334155); color: #fff;
  border-radius: 14px; padding: 28px 30px; margin-bottom: 26px; }
.cover .brand { font-size: 12px; letter-spacing: 2px; text-transform: uppercase; opacity: .8; }
.cover h1 { font-size: 26px; margin: 6px 0 2px; letter-spacing: -0.5px; }
.cover .meta { display: flex; gap: 22px; flex-wrap: wrap; margin-top: 14px; font-size: 12.5px; opacity: .95; }
h2.section-title { font-size: 16px; margin: 26px 0 10px; padding-bottom: 6px; border-bottom: 2px solid #eef2f7; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 20px;}
.kpi { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px 14px; }
.kpi-label { font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: .4px; }
.kpi-value { font-size: 22px; font-weight: 700; color: #111827; margin-top: 2px; }
table { width: 100%; border-collapse: collapse; margin: 8px 0 16px; }
th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid #eef2f7; vertical-align: top; }
th { background: #f8fafc; font-weight: 600; font-size: 12px; color: #475569; }
tr:nth-child(even) td { background: #fbfcfe; }
.badge { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 11px; font-weight: 700; }
.status-done { background: #dcfce7; color: #15803d; }
.status-due { background: #fef3c7; color: #b45309; }
.status-overdue { background: #fee2e2; color: #b91c1c; }
.status-blocked { background: #f3f4f6; color: #4b5563; }
.status-skipped { background: #f3f4f6; color: #4b5563; }
.mode-auto { color: #16a34a; font-weight: 600; }
.mode-assisted { color: #d97706; font-weight: 600; }
.mode-manual { color: #64748b; font-weight: 600; }
"""

def _esc(value) -> str:
    return _html_esc.escape(str(value if value is not None else ""), quote=True)

def _kpi(label, value):
    return f'<div class="kpi"><div class="kpi-label">{_esc(label)}</div><div class="kpi-value">{_esc(value)}</div></div>'

def _status_badge(status):
    cls = f"status-{status.lower()}"
    return f'<span class="badge {cls}">{_esc(status.upper())}</span>'

def _mode_span(mode):
    return f'<span class="mode-{mode}">{_esc(mode.capitalize())}</span>'

async def generate_cadence_report_html(site_id: str, cadence: str, period_key: str) -> str:
    state = await get_register_state(site_id, period_key)
    tasks = state.get("tasks", [])
    
    # Filter tasks by the target cadence (or cadences up to that)
    # Weekly Pulse -> weekly only
    # Monthly SEO Report -> weekly + monthly
    # Quarterly Strategy Review -> weekly + monthly + quarterly
    
    included_cadences = []
    report_title = ""
    if cadence == "weekly":
        included_cadences = ["weekly"]
        report_title = "Weekly SEO Pulse"
    elif cadence == "monthly":
        included_cadences = ["weekly", "monthly"]
        report_title = "Monthly SEO Report"
    elif cadence == "quarterly":
        included_cadences = ["weekly", "monthly", "quarterly"]
        report_title = "Quarterly Strategy Review"
    else:
        included_cadences = [cadence]
        report_title = f"{cadence.capitalize()} Report"
        
    filtered_tasks = [t for t in tasks if t["cadence"] in included_cadences]
    
    # Calculate summary for the filtered tasks
    done_count = sum(1 for t in filtered_tasks if t.get("derivedState") == "done")
    due_count = sum(1 for t in filtered_tasks if t.get("derivedState") == "due")
    overdue_count = sum(1 for t in filtered_tasks if t.get("derivedState") == "overdue")
    blocked_count = sum(1 for t in filtered_tasks if t.get("derivedState") in ["blocked", "skipped"])
    total_count = len(filtered_tasks)
    
    completion_rate = int((done_count / total_count * 100) if total_count > 0 else 0)
    
    kpis = "".join([
        _kpi("Completion", f"{completion_rate}%"),
        _kpi("Done", done_count),
        _kpi("Due", due_count),
        _kpi("Overdue / Blocked", overdue_count + blocked_count),
    ])
    
    task_rows = ""
    for t in filtered_tasks:
        task_rows += f'''
        <tr>
            <td><strong>{_esc(t.get("id"))}</strong><br>{_esc(t.get("title"))}</td>
            <td>{_mode_span(t.get("mode"))}</td>
            <td>{_esc(t.get("commitment"))}</td>
            <td>{_status_badge(t.get("derivedState"))}</td>
        </tr>
        '''
        
    html = f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
    <title>{_esc(report_title)} — {_esc(site_id)}</title><style>{_REPORT_CSS}</style></head><body>
    <div class="cover"><div class="brand">Execution Register</div>
    <h1>{_esc(report_title)}</h1>
    <div class="meta"><span>Site ID: <b>{_esc(site_id)}</b></span><span>Period: <b>{_esc(period_key)}</b></span>
    <span>Generated: {_esc(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))}</span></div></div>
    
    <h2 class="section-title">Execution Summary</h2>
    <div class="kpis">{kpis}</div>
    
    <h2 class="section-title">Task Register</h2>
    <table>
        <tr><th>Task</th><th>Mode</th><th>Commitment</th><th>Status</th></tr>
        {task_rows}
    </table>
    
    <footer>Generated by RankEngine — Honest Execution Register.</footer>
    </body></html>
    '''
    
    return html
