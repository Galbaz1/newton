"""Owner-scoped company and machine routes, mounted by the coordinator under /api."""

from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ._schemas import CompanyInput, MachineInput, MachinePatch, company_json, machine_json
from .db import get_db
from .models import Company, Machine, User
from .security import current_user, require_company, require_machine

router = APIRouter(tags=["companies"])


def bump_context(db: Session, machine_id: str) -> None:
    """Increment in SQL to avoid lost context-version increments under concurrent edits."""
    db.execute(
        update(Machine)
        .where(Machine.id == machine_id)
        .values(context_version=Machine.context_version + 1)
    )


@router.get("/companies")
def list_companies(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """List only the current account's companies as a raw array."""
    rows = db.scalars(
        select(Company).where(Company.owner_id == user.id).order_by(Company.created_at, Company.id)
    )
    return [company_json(row) for row in rows]


@router.post("/companies")
def create_company(
    data: CompanyInput, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Create a company whose owner is derived solely from the session."""
    company = Company(owner_id=user.id, **data.model_dump())
    db.add(company)
    db.commit()
    return company_json(company)


@router.get("/companies/{company_id}/machines")
def list_machines(
    company_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """List machines after authorizing the requested company."""
    require_company(db, user, company_id)
    rows = db.scalars(
        select(Machine)
        .where(Machine.company_id == company_id)
        .order_by(Machine.created_at, Machine.id)
    )
    return [machine_json(row) for row in rows]


@router.post("/companies/{company_id}/machines")
def create_machine(
    company_id: str,
    data: MachineInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Create a machine in an owned company with context version one."""
    require_company(db, user, company_id)
    machine = Machine(company_id=company_id, **data.model_dump())
    db.add(machine)
    db.commit()
    return machine_json(machine)


@router.get("/machines/{machine_id}")
def get_machine(machine_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Return an owned machine or an indistinguishable unknown/foreign 404."""
    return machine_json(require_machine(db, user, machine_id))


@router.patch("/machines/{machine_id}")
def patch_machine(
    machine_id: str,
    data: MachinePatch,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Correct machine descriptors and atomically advance its evidence context."""
    machine = require_machine(db, user, machine_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(machine, key, value)
    bump_context(db, machine.id)
    db.commit()
    db.refresh(machine)
    return machine_json(machine)
