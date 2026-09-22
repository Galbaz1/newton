"""Small durable checkpoints shared by API handlers and the local agent worker."""

from sqlalchemy import select

from ._schemas import project
from .db import utcnow
from .models import Machine
from .onboarding_models import CompanyProfile, IntakeItem, OnboardingRun


def known_installations(db, company_id: str) -> dict[str, list[str]]:
    """Resolve prior onboarding references only to still-owned company machines.

    References are case-insensitive. Conflicting identities remain a list so
    registration can reject ambiguity instead of silently selecting one machine.
    """
    owned = set(db.scalars(select(Machine.id).where(Machine.company_id == company_id)))
    references = {}
    for state in db.scalars(
        select(OnboardingRun.state).where(OnboardingRun.company_id == company_id)
    ):
        for reference, identifier in state.get("assets", {}).items():
            if identifier in owned:
                references.setdefault(reference.casefold(), set()).add(identifier)
    return {reference: sorted(identifiers) for reference, identifiers in references.items()}


def checkpoint(db, run: OnboardingRun, kind: str, message: str, **changes) -> None:
    """Persist an observed action and its associated state in one transaction."""
    latest = db.scalar(
        select(OnboardingRun.state).where(OnboardingRun.id == run.id).with_for_update()
    )
    state = {**(latest or {}), **changes}
    state["events"] = [
        *state.get("events", []),
        {
            "at": utcnow().isoformat(),
            "kind": kind,
            "message": message,
        },
    ][-300:]
    run.state, run.updated_at = state, utcnow()
    db.commit()
    from .observability import publish_onboarding

    publish_onboarding(db, run)


def run_json(db, run: OnboardingRun) -> dict:
    """Expose results and progress without private storage keys or provider traces."""
    result = project(
        run, "id company_id website data_class status stage summary created_at updated_at"
    )
    profile = db.get(CompanyProfile, run.company_id)
    result["profile"] = profile.content if profile else {}
    result["items"] = [
        project(
            item, "id filename sha256 kind status data_class machine_id source_id profile findings"
        )
        for item in db.scalars(
            select(IntakeItem).where(IntakeItem.run_id == run.id).order_by(IntakeItem.created_at)
        )
    ]
    for key in ("events", "questions", "pending_questions", "reviews"):
        result[key] = run.state.get(key, [])
    if run.state.get("agent_finished"):
        # Generated prose previously misstated counts and claimed unseen images were inspected.
        items = result["items"]
        ready = sum(i["status"] in {"ready", "needs_text"} for i in items)
        quarantined = sum(i["status"] == "quarantined" for i in items)
        errors = sum(i["status"] == "error" for i in items)
        images = [i for i in items if i["kind"] == "image"]
        inspected = sum(bool(i["profile"].get("visual_observation")) for i in images)
        questions = sum(q["state"] == "ready" for q in result["questions"])
        result["summary"] = (
            f"Behouden bestanden: {len(items)}. Daarvan {ready} klaargezet, "
            f"{quarantined} apart gehouden en {errors} met een verwerkingsfout. "
            f"Visueel bekeken afbeeldingen: {inspected} van {len(images)}. "
            f"Gekoppelde installaties: {len(run.state.get('assets', {}))}. "
            f"Beschikbare startvragen: {questions}. "
            "Bronbeoordelingen, ontbrekende informatie en voortgang staan hieronder."
        )
    return result
