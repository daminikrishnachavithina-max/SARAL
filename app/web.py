"""SARAL web backend: read-only scholarship discovery API."""
import json
from datetime import date
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from .eligibility import evaluate, load_criteria
from fastapi.responses import HTMLResponse
from .db import get_connection

app = FastAPI(
    title="SARAL",
    description="For Every Citizen — discover support opportunities.",
    version="0.1.0",
)


@app.get("/api/health")
def health():
    return {"status": "ok", "app": "SARAL"}


@app.get("/api/opportunities")
def opportunities(
    search: str = Query(default="", max_length=100),
    state: str = Query(default="", max_length=100),
    category: str = Query(default="", max_length=50),
):
    """List verified opportunities without changing the database."""
    today = date.today().isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, name, org_name, category, state, description,
                   official_url, apply_url, deadline, application_status,
                   funding, documents_json, verification_status,
                   last_checked_at, current_version
            FROM opportunities
            WHERE verification_status = 'verified'
              AND (deadline IS NULL OR deadline = '' OR deadline >= ?)
              AND lower(application_status) = 'open'
              AND (? = '' OR lower(name) LIKE '%' || lower(?) || '%'
                   OR lower(org_name) LIKE '%' || lower(?) || '%')
              AND (? = '' OR lower(COALESCE(state,'')) = lower(?))
              AND (? = '' OR lower(COALESCE(category,'')) = lower(?))
            ORDER BY deadline IS NULL, deadline ASC, name ASC
            """,
            (today, search, search, search, state, state, category, category),
        ).fetchall()

    results = []
    for row in rows:
        item = dict(row)
        item["documents"] = json.loads(item.pop("documents_json") or "[]")
        results.append(item)
    return {"count": len(results), "opportunities": results}


@app.get("/api/opportunities/{opportunity_id}")
def opportunity_detail(opportunity_id: int):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, name, org_name, category, state, description,
                   official_url, apply_url, deadline, application_status,
                   funding, documents_json, verification_status,
                   last_checked_at, current_version
            FROM opportunities WHERE id = ?
            """,
            (opportunity_id,),
        ).fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="Opportunity not found.")

        item = dict(row)
        item["documents"] = json.loads(item.pop("documents_json") or "[]")
        item["criteria"] = [
            dict(rule)
            for rule in conn.execute(
                """
                SELECT field, operator, value, label
                FROM criteria
                WHERE opportunity_id = ? AND version = ?
                ORDER BY id
                """,
                (opportunity_id, item["current_version"]),
            ).fetchall()
        ]
    return item


class EligibilityProfile(BaseModel):
    education_level: str | None = None
    income: float | None = None
    marks_percent: float | None = None


@app.post("/api/eligibility/check")
def check_eligibility(profile_data: EligibilityProfile):
    profile = profile_data.model_dump(exclude_none=True)
    today = date.today().isoformat()

    with get_connection() as conn:
        opportunities = conn.execute(
            """
            SELECT id, name, org_name, official_url, deadline,
                   application_status, verification_status
            FROM opportunities
            WHERE verification_status = 'verified'
              AND lower(application_status) = 'open'
              AND (deadline IS NULL OR deadline = '' OR deadline >= ?)
            ORDER BY deadline IS NULL, deadline ASC, name ASC
            """,
            (today,),
        ).fetchall()

        results = []

        for opportunity in opportunities:
            criteria = load_criteria(conn, opportunity["id"])
            assessment = evaluate(criteria, profile)

            results.append({
                "id": opportunity["id"],
                "name": opportunity["name"],
                "organization": opportunity["org_name"],
                "official_url": opportunity["official_url"],
                "result": assessment["overall"],
                "result_text": assessment["overall_text"],
                "criteria": assessment["criteria"],
                "note": assessment["note"],
            })

    return {
        "profile_fields_provided": list(profile.keys()),
        "count": len(results),
        "message": (
            "No verified open opportunities are currently available to check."
            if not results else
            "Results are based on the recorded eligibility criteria."
        ),
        "results": results,
    }
@app.get("/", response_class=HTMLResponse)
def home():
    return """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SARAL — For Every Citizen</title>
<style>
:root{color-scheme:light;--navy:#13263f;--teal:#087e83;--pale:#edf7f6;--ink:#243247;--muted:#657487}
*{box-sizing:border-box}
body{margin:0;background:#f6f8fb;color:var(--ink);font:16px/1.55 system-ui,Segoe UI,sans-serif}
header{background:var(--navy);color:white;padding:24px max(22px,calc((100% - 1050px)/2))}
.brand{font-size:28px;font-weight:800;letter-spacing:2px}
.tagline{color:#c8e8e7;margin-top:2px}
main{max-width:1050px;margin:38px auto;padding:0 20px}
.intro{background:white;padding:30px;border-radius:18px;border:1px solid #e1e8ef}
h1{font-size:clamp(27px,4vw,42px);line-height:1.15;color:var(--navy);margin:0 0 12px}
p{margin:8px 0}
.search{display:flex;gap:10px;margin-top:22px;flex-wrap:wrap}
input,select{flex:1;min-width:180px;padding:13px;border:1px solid #ccd7e2;border-radius:9px;font:inherit}\ninput{flex:1;min-width:180px;padding:13px;border:1px solid #ccd7e2;border-radius:9px;font:inherit}
button{padding:13px 20px;border:0;border-radius:9px;background:var(--teal);color:white;font:inherit;font-weight:700;cursor:pointer}
button:focus,input:focus{outline:3px solid #a8dedd;outline-offset:2px}
#status{color:var(--muted);margin:22px 0}
#results{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,290px),1fr));gap:16px}
.card{background:white;padding:21px;border:1px solid #e1e8ef;border-radius:14px;overflow-wrap:anywhere}
.card h2{font-size:19px;color:var(--navy);margin:0 0 8px}
.meta{color:var(--muted);font-size:14px}
a{color:var(--teal);font-weight:650}
.note{margin-top:28px;background:var(--pale);padding:17px;border-radius:12px;font-size:14px}
footer{color:var(--muted);font-size:13px;margin:25px 0 40px}
</style>
</head>
<body>
<header><div class="brand">SARAL</div><div class="tagline">For Every Citizen</div></header>
<main>
<section class="intro">
<h1>Find support for your next step.</h1>
<p>Discover scholarships, jobs, government schemes, healthcare, housing, and other support opportunities in one place.</p>
<form class="search" id="searchForm">
<select id="category" aria-label="Choose support category">
<option value="">All categories</option>
<option value="education">Education & scholarships</option>
<option value="jobs">Jobs & careers</option>
<option value="government schemes">Government schemes</option>
<option value="healthcare">Health & welfare</option>
<option value="housing">Housing support</option>
<option value="agriculture">Agriculture</option>
<option value="financial assistance">Financial assistance</option>
<option value="legal support">Legal support</option>
</select>
<select id="state" aria-label="Choose state">
<option value="">All states</option>
<option value="Andhra Pradesh">Andhra Pradesh</option>
<option value="Telangana">Telangana</option>
<option value="Tamil Nadu">Tamil Nadu</option>
<option value="Karnataka">Karnataka</option>
<option value="Maharashtra">Maharashtra</option>
<option value="Delhi">Delhi</option>
</select>
<input id="query" aria-label="Search opportunities" placeholder="Search by name or organisation">
<button type="submit">Search</button>
</form>
</section>
<p id="status" role="status">Loading opportunities…</p>
<section id="results" aria-live="polite"></section>
<div class="note"><strong>Please note:</strong> Listings depend on the information currently recorded in SARAL. Check the official source for current conditions before applying. A listing or eligibility assessment does not guarantee selection or funding.</div>
<footer>SARAL is an independent support-discovery project. Always verify requirements with the responsible organisation.</footer>
</main>
<script>
const statusBox=document.getElementById('status');
const results=document.getElementById('results');
function addText(parent,tag,text,className){
 const el=document.createElement(tag); el.textContent=text;
 if(className) el.className=className; parent.appendChild(el); return el;
}
async function load(query=''){
 statusBox.textContent='Loading opportunities…'; results.replaceChildren();
 try{
  const category=document.getElementById('category').value;
  const state=document.getElementById('state').value;
  const params=new URLSearchParams({search:query,category:category,state:state});
  const response=await fetch('/api/opportunities?'+params.toString());
  if(!response.ok) throw new Error('Request failed');
  const data=await response.json();
  statusBox.textContent=data.count+' open, verified opportunity/ies found.';
  if(!data.count) addText(results,'p','No matching opportunities are currently recorded.');
  for(const item of data.opportunities){
   const card=document.createElement('article'); card.className='card';
   addText(card,'h2',item.name);
   addText(card,'p',item.org_name);
   if(item.description) addText(card,'p',item.description);
   addText(card,'p','Deadline: '+(item.deadline||'Not listed'));
   if(item.funding) addText(card,'p','Support: '+item.funding);
   addText(card,'p','Verification: '+item.verification_status+' · Version '+item.current_version,'meta');
   const link=document.createElement('a'); link.textContent='View official information';
   link.href=item.official_url; link.target='_blank'; link.rel='noopener noreferrer';
   
card.appendChild(link);

const detailsButton = document.createElement('button');
detailsButton.type = 'button';
detailsButton.textContent = 'View eligibility & documents';
detailsButton.style.marginTop = '12px';

detailsButton.addEventListener('click', async () => {
  detailsButton.disabled = true;
  detailsButton.textContent = 'Loading details…';

  try {
    const response = await fetch('/api/opportunities/' + item.id);
    if (!response.ok) throw new Error('Could not load details');

    const detail = await response.json();

    const details = document.createElement('div');
    details.className = 'note';

    addText(details, 'h3', 'Eligibility & required documents');

    if (detail.criteria && detail.criteria.length) {
      addText(details, 'h4', 'Eligibility criteria');
      detail.criteria.forEach(rule => {
        addText(details, 'p', rule.label);
      });
    } else {
      addText(details, 'p', 'No eligibility criteria recorded yet.');
    }

    if (detail.documents && detail.documents.length) {
      addText(details, 'h4', 'Required documents');
      detail.documents.forEach(doc => addText(details, 'p', '• ' + doc));
    } else {
      addText(details, 'p', 'No document list recorded yet.');
    }

    detailsButton.replaceWith(details);
  } catch (error) {
    detailsButton.textContent = 'Could not load details — try again';
    detailsButton.disabled = false;
  }
});

card.appendChild(detailsButton);
results.appendChild(card);

  }
 }catch(e){statusBox.textContent='Could not load opportunities. Check that the SARAL server is running.';}
}
document.getElementById('searchForm').addEventListener('submit',e=>{
 e.preventDefault(); load(document.getElementById('query').value.trim());
});
load();
</script>
</body>
</html>
"""
