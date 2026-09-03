"""Phase 6 routers — meta (health + metadata contract)."""

from fastapi import APIRouter, Depends

from ..contracts.common import ProvenanceContract
from ..contracts.dashboard import MetaDoc
from ..services import meta as meta_service
from ..services.db import provenance_contract

router = APIRouter(tags=["meta"])


def _get_db():
    # Lazy import to avoid a module-load cycle with main.py.
    from ..services.db import get_db
    from ..settings import get_settings

    yield from get_db(get_settings())


@router.get("/health", response_model=ProvenanceContract)
def health(cur=Depends(_get_db)):
    """Liveness + read-only reconciliation anchors against locked surfaces."""
    return provenance_contract(cur)


@router.get("/meta", response_model=MetaDoc)
def meta(cur=Depends(_get_db)):
    """Provenance/limitation/empty-state metadata for the app shell."""
    return meta_service.build_meta(cur)


@router.get("/meta/dimensions")
def meta_dimensions(cur=Depends(_get_db)):
    """Bounded filter-dimension options (department/category/store/state/region)."""
    return meta_service.dimensions(cur)