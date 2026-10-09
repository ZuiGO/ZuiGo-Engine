from enum import Enum
from pydantic import BaseModel
from typing import List, Optional, Literal, Any

class Cadence(str, Enum):
    weekly = "weekly"
    monthly = "monthly"
    quarterly = "quarterly"

class Pillar(str, Enum):
    technical = "technical"
    onpage = "onpage"
    offpage = "offpage"
    reporting = "reporting"

class Mode(str, Enum):
    auto = "auto"
    assisted = "assisted"
    manual = "manual"

class SourceId(str, Enum):
    gsc = "gsc"
    ga4 = "ga4"
    crawl = "crawl"
    serp_snapshot = "serp_snapshot"
    lighthouse = "lighthouse"
    crux = "crux"
    firecrawl = "firecrawl"
    keyword_planner = "keyword_planner"
    manual = "manual"

class ScheduleHint(BaseModel):
    week: Optional[Literal[1, 2, 3, 4]] = None
    cron: Optional[str] = None

class SeoTaskDef(BaseModel):
    id: str
    cadence: Cadence
    pillar: Pillar
    title: str
    commitment: str
    howItRuns: str
    mode: Mode
    sources: List[SourceId]
    doneWhen: str
    scheduleHint: ScheduleHint = ScheduleHint()
    dependsOn: Optional[List[str]] = None

class SiteTaskConfig(BaseModel):
    siteId: str
    taskId: str
    enabled: bool = True
    disabledReason: Optional[str] = None

class EvidenceRef(BaseModel):
    kind: Literal["audit", "snapshot", "diff", "report", "register_entry", "url"]
    ref: str

class Metric(BaseModel):
    key: str
    value: Any
    unit: Optional[str] = None
    source: SourceId
    fetchedAt: str
    periodStart: str
    periodEnd: str
    verified: bool

class RunStatus(str, Enum):
    done = "done"
    skipped = "skipped"
    failed = "failed"
    
class TaskTrigger(str, Enum):
    schedule = "schedule"
    manual = "manual"

class TaskRun(BaseModel):
    id: str
    siteId: str
    taskId: str
    periodKey: str
    status: RunStatus
    startedAt: str
    finishedAt: str
    triggeredBy: TaskTrigger
    skipReason: Optional[str] = None
    evidence: List[EvidenceRef] = []
    metrics: List[Metric] = []
    notes: Optional[str] = None

class FindingSeverity(str, Enum):
    blocking = "blocking"
    high = "high"
    medium = "medium"
    low = "low"

class FindingStatus(str, Enum):
    open = "open"
    fixed = "fixed"
    accepted = "accepted"

class Finding(BaseModel):
    id: str
    siteId: str
    taskId: str
    severity: FindingSeverity
    check: str
    url: Optional[str] = None
    firstSeen: str
    lastSeen: str
    status: FindingStatus
    acceptedReason: Optional[str] = None
    fixRef: Optional[str] = None
