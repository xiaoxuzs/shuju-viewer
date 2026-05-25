"""Bottom-Up dataset overview endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.bu.deps import require_bu_dataset
from app.bu.services.overview_service import get_overview, get_rt_mz_heatmap
from app.schemas import BuOverviewOut, BuRtMzHeatmapOut

router = APIRouter()


@router.get("/datasets/{slug}/overview", response_model=BuOverviewOut)
def overview(slug: str, session: Session = Depends(get_db)) -> BuOverviewOut:
    dataset = require_bu_dataset(session, slug)
    return get_overview(session, dataset)


@router.get("/datasets/{slug}/overview/rt-mz", response_model=BuRtMzHeatmapOut)
def rt_mz(
    slug: str,
    run_id: int | None = None,
    q_max: float | None = None,
    bins_rt: int = Query(default=80, ge=10, le=200),
    bins_mz: int = Query(default=80, ge=10, le=200),
    decoy: bool = False,
    session: Session = Depends(get_db),
) -> BuRtMzHeatmapOut:
    dataset = require_bu_dataset(session, slug)
    extra = dataset.get("extra_metadata") if isinstance(dataset.get("extra_metadata"), dict) else {}
    effective_q_max = q_max if q_max is not None else float(extra.get("q_value_cutoff") or 0.01)
    return get_rt_mz_heatmap(
        session,
        dataset,
        run_id=run_id,
        q_max=effective_q_max,
        bins_rt=bins_rt,
        bins_mz=bins_mz,
        decoy=decoy,
    )
