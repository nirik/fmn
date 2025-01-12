import logging
from importlib import metadata

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from fmn.api import api_models
from fmn.api.auth import Identity, get_identity
from fmn.api.database import gen_db_session
from fmn.api.distgit import DistGitClient, get_distgit_client
from fmn.core.constants import ArtifactType
from fmn.database.migrations.main import alembic_migration
from fmn.database.model import User
from fmn.rules.notification import Notification
from fmn.rules.requester import Requester

from .utils import db_rule_from_api_rule, gen_requester, get_last_messages

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/applications", response_model=list[str], tags=["misc"])
def get_applications():
    entrypoints = metadata.entry_points().select(group="fedora.messages")
    applications = set()
    for ep in entrypoints:
        msg_cls = ep.load()
        try:
            app_name = msg_cls.app_name.fget(None)
            if app_name is None:
                raise ValueError("app_name is None")
        except Exception:
            # Sometimes the schema hasn't set the app_name. Fallback on the entry point name.
            app_name = ep.name.partition(".")[0]
        applications.add(app_name)

    # we will always have the base message in there, so lets discard that
    applications.discard("base")
    applications = list(applications)
    applications.sort(key=lambda name: name.lower())

    return applications


@router.get("/artifacts/owned", response_model=list[dict[str, str]], tags=["misc"])
async def get_owned_artifacts(
    users: list[str] = Query(default=[]),
    groups: list[str] = Query(default=[]),
    distgit_client: DistGitClient = Depends(get_distgit_client),
):
    if users:
        return await distgit_client.get_owned(users, "user")
    elif groups:
        return await distgit_client.get_owned(groups, "group")
    else:
        return []


@router.get("/artifacts", response_model=list[api_models.ArtifactOptionsGroup], tags=["misc"])
async def get_artifacts(
    name: str, distgit_client: DistGitClient = Depends(get_distgit_client)
):  # pragma: no cover todo
    artifacts = [
        {
            "label": "RPMs",
            "options": [],
        },
        {
            "label": "Containers",
            "options": [],
        },
        {
            "label": "Modules",
            "options": [],
        },
        {
            "label": "Flatpaks",
            "options": [],
        },
    ]
    namespaces = [at.value for at in ArtifactType]
    projects = await distgit_client.get_projects(pattern=name)
    for project in projects:
        for index, namespace in enumerate(namespaces):
            if project["namespace"] == namespace:
                artifacts[index]["options"].append(
                    {
                        "label": project["name"],
                        "value": {"type": namespace, "name": project["name"]},
                    }
                )
    return artifacts


@router.post("/rule-preview", response_model=list[Notification], tags=["users/rules"])
async def preview_rule(
    rule: api_models.RulePreview,
    identity: Identity = Depends(get_identity),
    requester: Requester = Depends(gen_requester),
):
    if identity.name is None:
        raise HTTPException(status_code=403, detail="You need to be logged in")

    # Make sure each GenerationRule has one destination, otherwise no notifications will
    # be produced (or too many).
    for gr in rule.generation_rules:
        gr.destinations = [api_models.Destination(protocol="preview", address="preview")]

    log.debug("Previewing rule:", rule)
    user = User(name=identity.name)
    rule_db = db_rule_from_api_rule(rule, user)
    rule_db.id = 0
    notifs = []
    # TODO make the delta a setting
    # TODO: this takes ridiculously long.
    async for message in get_last_messages(1):
        log.debug(f"Processing message: {message.body}")
        async for notif in rule_db.handle(message, requester):
            notifs.append(notif)
    return notifs


@router.get("/healthz/live", tags=["healthz"])
async def liveness_check():
    return {"detail": "OK"}


@router.get("/healthz/ready", tags=["healthz"])
async def readiness_check(db_session: AsyncSession = Depends(gen_db_session)):
    try:
        needs_upgrade = await alembic_migration.needs_upgrade(db_session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if needs_upgrade:
        raise HTTPException(status_code=500, detail="Database schema needs to be upgraded")
    else:
        return {"detail": "OK"}
