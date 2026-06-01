import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services.db_manager import init_db
from services import project_manager as pm
from services import history_manager as hm
from services import query_engine as qe
from services import land_info as li
from services import compliance_engine as ce


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="law-qa", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── /api/query ─────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    project_id: int
    question: str
    image_base64: str | None = None


@app.post("/api/query")
def run_query(req: QueryRequest):
    if not pm.get(req.project_id):
        raise HTTPException(status_code=404, detail="project not found")

    result = qe.answer(req.question, image_base64=req.image_base64)

    history = hm.save(
        project_id=req.project_id,
        question=req.question,
        answer=result["answer"],
        source_law_ids=result.get("source_law_ids"),
        has_image=req.image_base64 is not None,
        confidence=result.get("confidence"),
    )

    return {
        "answer": result["answer"],
        "source_laws": result.get("source_laws", []),
        "source_law_ids": result.get("source_law_ids", []),
        "confidence": result.get("confidence"),
        "history_id": history["id"],
    }


# ── /api/land-info ─────────────────────────────────────────────────────────────

@app.get("/api/land-info")
def get_land_info(address: str = Query(..., min_length=1)):
    return li.get_land_info(address)


# ── /api/compliance ────────────────────────────────────────────────────────────

class ComplianceRequest(BaseModel):
    address: str = ""
    building_use: str = ""
    total_floor_area: float | None = None
    floors: int | None = None


@app.post("/api/compliance")
def run_compliance(req: ComplianceRequest):
    return ce.check(
        address=req.address,
        building_use=req.building_use,
        total_floor_area=req.total_floor_area,
        floors=req.floors,
    )


# ── /api/projects ──────────────────────────────────────────────────────────────

class ProjectBody(BaseModel):
    name: str
    description: str | None = None


@app.get("/api/projects")
def list_projects():
    return pm.list_all()


@app.post("/api/projects", status_code=201)
def create_project(body: ProjectBody):
    return pm.create(body.name, body.description)


@app.delete("/api/projects/{project_id}", status_code=204)
def delete_project(project_id: int):
    if not pm.delete(project_id):
        raise HTTPException(status_code=404, detail="project not found")


# ── /api/projects/{id}/history ─────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/history")
def get_project_history(project_id: int):
    if not pm.get(project_id):
        raise HTTPException(status_code=404, detail="project not found")
    return hm.get_by_project(project_id)


# ── /api/history/search ────────────────────────────────────────────────────────

@app.get("/api/history/search")
def search_history(
    q: str = Query(..., min_length=1),
    project_id: int | None = None,
):
    return hm.search(q, project_id=project_id)


# ── 직접 실행 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
