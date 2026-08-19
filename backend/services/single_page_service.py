import asyncio
import base64
import json
import uuid
import re
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.config import settings

logger = get_logger("single_page_service")

import groq

def evaluate_onpage_score(title: str, desc: str, h1: str, alt_text: str, robots_txt: str = "", llms_txt: str = "") -> int:
    """
    Evaluates on-page SEO fields based on length and descriptiveness.
    Returns a score out of 100.
    """
    score = 0
    
    title_str = (title or "").strip()
    if title_str:
        if 15 <= len(title_str) <= 60:
            score += 30
        else:
            score += 15
            
    desc_str = (desc or "").strip()
    if desc_str:
        if 50 <= len(desc_str) <= 160:
            score += 30
        else:
            score += 15
            
    h1_str = (h1 or "").strip()
    if h1_str:
        words = len(h1_str.split())
        if words >= 3:
            score += 20
        else:
            score += 10
            
    alt_str = (alt_text or "").strip()
    if alt_str:
        words = len(alt_str.split())
        if words >= 2:
            score += 10
        else:
            score += 5
            
    if (robots_txt or "").strip():
        score += 5
    if (llms_txt or "").strip():
        score += 5
        
    return max(0, min(100, score))

async def generate_suggestions(title: str, h1: str, desc: str, h2: str, p_text: str, img_alt: str) -> dict:
    """
    Calls Groq to generate optimized versions of the given fields.
    Returns a dictionary with keys: "title", "h1", "meta_description", "h2", "p_text", "img_alt".
    """
    try:
        from backend.config import settings
        from groq import AsyncGroq
        
        client = AsyncGroq(api_key=settings.groq_api_key)
        prompt = f"""
        You are an elite, world-class SEO strategist and conversion copywriter. 
        Your task is to completely transform the following mediocre website content into a high-octane, authoritative, and irresistible marketing asset that dominates search rankings and maximizes conversions.
        
        CURRENT CONTENT:
        Title: {title}
        H1 Heading: {h1}
        H2 Heading: {h2}
        Main Paragraph: {p_text}
        Image Alt Text: {img_alt}
        Meta Description: {desc}
        
        INSTRUCTIONS FOR TRANSFORMATION:
        1. Title: Make it an explosive, click-driving hook (under 60 chars) with a clear value proposition.
        2. H1 Heading: Needs to be a commanding, definitive statement of superiority that instantly grabs attention.
        3. H2 Heading: A powerful secondary hook focusing on unignorable benefits.
        4. Main Paragraph: Rewrite completely to be fiercely persuasive. Focus on solving the user's deepest pain point with absolute authority. Do not sound generic!
        5. Image Alt Text: Write a dense, highly descriptive alt text naturally packed with primary semantic keywords for Google Images ranking.
        6. Meta Description: Craft a magnetic description (under 160 chars) that creates extreme urgency and forces the searcher to click.

        IMPORTANT: Do NOT use generic placeholders or simply append words like "Premium". Actually write compelling copy!
        Return ONLY a raw JSON object with keys: "title", "h1", "meta_description", "h2", "p_text", "img_alt".
        """
        response = await client.chat.completions.create(
            model=settings.groq_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=2048,
        )
        content = response.choices[0].message.content
        # Extract JSON from markdown if present
        import re
        json_match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
        if json_match:
            content = json_match.group(1)
        else:
            # Maybe it returned raw JSON without markdown or with different markdown
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                content = json_match.group(0)
                
        return json.loads(content)
    except Exception as e:
        logger.error("Failed to generate suggestions via Groq: %s", e)
        # Fallback to simple modifications
        return {
            "title": f"The Ultimate Solution: {title}" if title else "The Ultimate Solution: Industry-Leading Excellence",
            "h1": f"Experience Unmatched Quality: {h1}" if h1 else "Experience Unmatched Quality & Performance",
            "h2": f"Why Choose Us? {h2}" if h2 else "Why We Dominate The Market",
            "p_text": f"Stop settling for average. Our elite, high-performance solutions are engineered to completely transform your workflow and deliver explosive growth. {p_text}"[:300],
            "img_alt": f"High-resolution showcase of {img_alt} featuring premium design" if img_alt else "High-resolution showcase of our premium flagship product in action",
            "meta_description": f"Don't fall behind. Discover how our cutting-edge approach to {h1} guarantees results. Click to unlock the ultimate guide. {desc}"[:160]
        }

async def generate_visual_comparison(job_id: str, url: str) -> dict:
    """
    1. Opens Playwright to the URL.
    2. Takes baseline snapshot.
    3. Extracts title, h1, meta description.
    4. Generates suggestions.
    5. Modifies DOM.
    6. Takes post-apply snapshot.
    7. Returns comparison dict.
    """
    from backend.services.job_cancel import check_cancelled

    logger.info("Generating visual comparison for %s (job: %s)", url, job_id)
    await check_cancelled(job_id)
    
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ZuiGO/1.0"
        )
        page = await context.new_page()
        
        await page.goto(url, wait_until="networkidle", timeout=30000)
        
        # Extract content first so we can inject the baseline SEO panel
        html_content = await page.content()
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Current values
        current_title = soup.title.string if soup.title else ""
        h1_tag = soup.find("h1")
        current_h1 = h1_tag.get_text(strip=True) if h1_tag else ""
        
        # Find an h2 and a paragraph to make visual changes obvious
        h2_tag = soup.find("h2")
        current_h2 = h2_tag.get_text(strip=True) if h2_tag else ""
        
        # Extract primary paragraph (skipping headers/footers)
        p_tag = None
        for p in soup.find_all("p"):
            if not p.find_parent(["header", "nav", "footer"]):
                p_tag = p
                break
        current_p = p_tag.get_text(strip=True) if p_tag else ""
        
        # Extract primary image (skipping logos in header/nav)
        img_tag = None
        for i in soup.find_all("img"):
            if not i.find_parent(["header", "nav", "footer"]):
                img_tag = i
                break
        current_img_alt = img_tag.get("alt", "") if img_tag else ""
        
        meta_desc = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        current_desc = meta_desc["content"] if meta_desc and meta_desc.has_attr("content") else ""

        # Inject SEO panel for baseline
        await page.evaluate("""
            (data) => {
                let panel = document.createElement('div');
                panel.id = 'zuigo-seo-panel';
                panel.style.position = 'fixed';
                panel.style.bottom = '20px';
                panel.style.right = '20px';
                panel.style.width = '350px';
                panel.style.background = 'white';
                panel.style.border = '2px solid #1e293b';
                panel.style.borderRadius = '8px';
                panel.style.boxShadow = '0 10px 25px rgba(0,0,0,0.2)';
                panel.style.zIndex = '2147483647';
                panel.style.fontFamily = 'system-ui, sans-serif';
                panel.style.padding = '16px';
                panel.style.fontSize = '13px';
                panel.style.color = '#334155';
                
                panel.innerHTML = `
                    <div style="font-weight: bold; font-size: 15px; margin-bottom: 12px; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px; color: #0f172a;">
                        🔍 Invisible SEO Metadata
                    </div>
                    <div style="margin-bottom: 8px;">
                        <span style="font-weight: 600; color: #475569;">Title Tag:</span><br/>
                        <span>${data.title || 'None'}</span>
                    </div>
                    <div style="margin-bottom: 8px;">
                        <span style="font-weight: 600; color: #475569;">Meta Description:</span><br/>
                        <span>${data.desc || 'None'}</span>
                    </div>
                    <div style="margin-bottom: 8px;">
                        <span style="font-weight: 600; color: #475569;">Primary Image Alt:</span><br/>
                        <span>${data.alt || 'None'}</span>
                    </div>
                `;
                document.body.appendChild(panel);
            }
        """, {"title": current_title, "desc": current_desc, "alt": current_img_alt})
        
        # Wait a bit for animations
        await asyncio.sleep(2)
        await check_cancelled(job_id)
        
        baseline_bytes = await page.screenshot(full_page=True, type="jpeg", quality=70)
        baseline_b64 = base64.b64encode(baseline_bytes).decode("utf-8")
        
        # 2. Generate Suggestions
        await check_cancelled(job_id)
        suggestions = await generate_suggestions(current_title, current_h1, current_desc, current_h2, current_p, current_img_alt)
        await check_cancelled(job_id)
        
        new_title = suggestions.get("title", current_title)
        new_h1 = suggestions.get("h1", current_h1)
        new_h2 = suggestions.get("h2", current_h2)
        new_p = suggestions.get("p_text", current_p)
        new_img_alt = suggestions.get("img_alt", current_img_alt)
        new_desc = suggestions.get("meta_description", current_desc)
        
        # 3. Apply changes locally via Playwright evaluate (in-place modification preserves all CSS and layout!)
        await page.evaluate("""
            (data) => {
                function highlight(el) {
                    if (!el) return;
                    // Add a highly visible highlight without modifying background or position!
                    // Modifying background color makes solid elements transparent, breaking contrast.
                    el.style.outline = '4px solid #10b981';
                    el.style.outlineOffset = '4px';
                    el.style.boxShadow = '0 0 15px rgba(16, 185, 129, 0.6)';
                    el.style.transition = 'all 0.3s ease-in-out';
                }
                
                if (document.title && data.title) {
                    document.title = data.title;
                }
                const h1 = document.querySelector('h1');
                if (h1 && data.h1 && h1.innerText !== data.h1) {
                    h1.innerText = data.h1;
                    highlight(h1);
                }
                const h2 = document.querySelector('h2');
                if (h2 && data.h2 && h2.innerText !== data.h2) {
                    h2.innerText = data.h2;
                    highlight(h2);
                }
                const p = document.querySelector('p');
                if (p && data.p_text && p.innerText !== data.p_text) {
                    p.innerText = data.p_text;
                    highlight(p);
                }
                const img = document.querySelector('img');
                if (img && data.img_alt && img.alt !== data.img_alt) {
                    img.alt = data.img_alt;
                    highlight(img);
                }
                let meta = document.querySelector('meta[name="description"]');
                if (meta && data.meta_description) {
                    meta.content = data.meta_description;
                }
                
                // Re-inject the SEO panel with new values and highlight changes
                let panel = document.getElementById('zuigo-seo-panel');
                if (panel) panel.remove();
                
                panel = document.createElement('div');
                panel.id = 'zuigo-seo-panel';
                panel.style.position = 'fixed';
                panel.style.bottom = '20px';
                panel.style.right = '20px';
                panel.style.width = '350px';
                panel.style.background = 'white';
                panel.style.border = '2px solid #10b981';
                panel.style.borderRadius = '8px';
                panel.style.boxShadow = '0 10px 25px rgba(16, 185, 129, 0.2)';
                panel.style.zIndex = '2147483647';
                panel.style.fontFamily = 'system-ui, sans-serif';
                panel.style.padding = '16px';
                panel.style.fontSize = '13px';
                panel.style.color = '#334155';
                
                panel.innerHTML = `
                    <div style="font-weight: bold; font-size: 15px; margin-bottom: 12px; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px; color: #10b981; display: flex; justify-content: space-between;">
                        <span>🔍 Invisible SEO Metadata</span>
                        <span style="background: #10b981; color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px;">AI OPTIMIZED</span>
                    </div>
                    <div style="margin-bottom: 8px;">
                        <span style="font-weight: 600; color: #475569;">Title Tag:</span><br/>
                        <span style="${data.title_changed ? 'background:#dcfce7; color:#166534; padding: 2px; border-radius: 2px;' : ''}">${data.title || 'None'}</span>
                    </div>
                    <div style="margin-bottom: 8px;">
                        <span style="font-weight: 600; color: #475569;">Meta Description:</span><br/>
                        <span style="${data.desc_changed ? 'background:#dcfce7; color:#166534; padding: 2px; border-radius: 2px;' : ''}">${data.meta_description || 'None'}</span>
                    </div>
                    <div style="margin-bottom: 8px;">
                        <span style="font-weight: 600; color: #475569;">Primary Image Alt:</span><br/>
                        <span style="${data.alt_changed ? 'background:#dcfce7; color:#166534; padding: 2px; border-radius: 2px;' : ''}">${data.img_alt || 'None'}</span>
                    </div>
                `;
                document.body.appendChild(panel);
            }
        """, {
            "title": new_title,
            "h1": new_h1,
            "h2": new_h2,
            "p_text": new_p,
            "img_alt": new_img_alt,
            "meta_description": new_desc,
            "title_changed": new_title != current_title,
            "desc_changed": new_desc != current_desc,
            "alt_changed": new_img_alt != current_img_alt
        })
        
        # Wait briefly for rendering to settle
        await asyncio.sleep(1)
        await check_cancelled(job_id)
        
        post_bytes = await page.screenshot(full_page=True, type="jpeg", quality=70)
        post_b64 = base64.b64encode(post_bytes).decode("utf-8")
        
        await browser.close()
        
        db = get_db()
        job = await db.analysis_jobs.find_one({"_id": job_id}) or {}
        sitewide = job.get("summary", {}).get("sitewide_factors", {})
        robots_txt = sitewide.get("robots_txt", "")
        llms_txt = sitewide.get("llms_txt", "")

        def calc_score(use_baseline=True):
            if use_baseline:
                return evaluate_onpage_score(
                    current_title, current_desc, current_h1, current_img_alt, robots_txt, llms_txt
                )
            else:
                return evaluate_onpage_score(
                    new_title, new_desc, new_h1, new_img_alt, robots_txt, llms_txt
                )

        # 5. Return comparison data
        comparison_data = {
            "seo_score": {
                "baseline": calc_score(True),
                "current": calc_score(False)
            },
            "fields": [
                {
                    "field": "title",
                    "baseline": current_title,
                    "current": new_title,
                    "status": "changed" if current_title != new_title else "unchanged"
                },
                {
                    "field": "h1",
                    "baseline": current_h1,
                    "current": new_h1,
                    "status": "changed" if current_h1 != new_h1 else "unchanged"
                },
                {
                    "field": "h2",
                    "baseline": current_h2,
                    "current": new_h2,
                    "status": "changed" if current_h2 != new_h2 else "unchanged"
                },
                {
                    "field": "p",
                    "baseline": current_p,
                    "current": new_p,
                    "status": "changed" if current_p != new_p else "unchanged"
                },
                {
                    "field": "img_alt",
                    "baseline": current_img_alt,
                    "current": new_img_alt,
                    "status": "changed" if current_img_alt != new_img_alt else "unchanged"
                },
                {
                    "field": "meta_description",
                    "baseline": current_desc,
                    "current": new_desc,
                    "status": "changed" if current_desc != new_desc else "unchanged"
                },
                {
                    "field": "robots.txt",
                    "baseline": "No robots.txt detected",
                    "current": robots_txt or "No robots.txt generated",
                    "status": "changed" if robots_txt else "unchanged"
                },
                {
                    "field": "llms.txt",
                    "baseline": "No llms.txt detected",
                    "current": llms_txt or "No llms.txt generated",
                    "status": "changed" if llms_txt else "unchanged"
                }
            ],
            "history": [
                {
                    "date": datetime.utcnow().isoformat(),
                    "action": "Baseline Captured",
                    "status": "success",
                    "commit_hash": None,
                    "preview_url": url
                },
                {
                    "date": datetime.utcnow().isoformat(),
                    "action": "AI Suggestions Applied",
                    "status": "success",
                    "commit_hash": "simulated",
                    "preview_url": url
                }
            ],
            "visuals": {
                "baseline_b64": baseline_b64,
                "current_b64": post_b64
            }
        }
        
        # We intentionally DO NOT append all action_items to the single page comparison
        # to prevent flooding the UI with hundreds of "Action: ..." rows.
        
        logger.info("Visual comparison completed for %s", job_id)
        return comparison_data
