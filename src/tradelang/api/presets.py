"""Local preset routes and selection resolution shared by inspection and runs."""

from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Response

from ..model import Problem
from ..persistence import LibraryError
from ..persistence.presets import Presets
from ..run_config import Origin, RunSettings, merge_settings
from .contracts import UuidText
from .library import Cursor, DisplayName, Limit, Page, RevisionNumber


class PresetWrite(DisplayName):
    settings: RunSettings
    dataset_id: UuidText | None = None
    profile_dataset_id: UuidText | None = None


class PresetUpdate(PresetWrite):
    expected_revision: RevisionNumber


class RunPreset(PresetWrite):
    id: UuidText
    revision: RevisionNumber
    created_at: str
    updated_at: str


def preset_routes(presets: Presets):
    router = APIRouter(prefix="/api/v1/run-presets")

    def fields(body):
        values = body.model_dump(exclude={"expected_revision"})
        for key in ("dataset_id", "profile_dataset_id"):
            if values[key] is not None:
                values[key] = str(UUID(values[key]))
        return values

    @router.get("", response_model=Page[RunPreset])
    def list_presets(limit: Limit = 50, cursor: Cursor = None):
        return presets.list(limit, cursor)

    @router.post("", status_code=201, response_model=RunPreset)
    def create_preset(body: PresetWrite, response: Response):
        preset = presets.write(fields(body))
        response.headers["Location"] = f"/api/v1/run-presets/{preset['id']}"
        return preset

    @router.get("/{ident}", response_model=RunPreset)
    def read_preset(ident: UUID):
        return presets.read(str(ident))

    @router.put("/{ident}", response_model=RunPreset)
    def update_preset(ident: UUID, body: PresetUpdate):
        preset = presets.write(
            fields(body), ident=str(ident), expected_revision=body.expected_revision
        )
        return preset

    return router


@dataclass(frozen=True)
class SelectedRun:
    dataset_id: str | None
    profile_dataset_id: str | None
    settings: RunSettings | None
    origins: dict[str, Origin]
    preset: dict | None


def resolve_feed_ids(feed_ids, resolver):
    feeds = {}
    for name, ident in sorted(feed_ids.items()):
        dataset = resolver(UUID(ident))
        if dataset is None:
            raise LibraryError(
                404, "E_DATASET_NOT_FOUND", f"Unknown dataset for feed {name}"
            )
        feeds[name] = dataset
    return feeds


def select_run(body, presets: Presets | None):
    preset = {}
    if (body.preset_id is None) != (body.preset_revision is None):
        raise LibraryError(
            422, "E_PRESET_REVISION", "Supply both the run preset ID and its revision"
        )
    if body.preset_id is not None:
        if presets is None:
            raise LibraryError(
                404, "E_PRESET_NOT_FOUND", "Run presets require a local library"
            )
        preset = presets.read(str(UUID(body.preset_id)))
        if preset["revision"] != body.preset_revision:
            raise LibraryError(
                409, "E_PRESET_CONFLICT", "The run preset has a newer revision"
            )

    def dataset_id(field):
        explicit = getattr(body, field)
        if field in body.model_fields_set:
            return str(UUID(explicit)) if explicit is not None else None
        return preset.get(field)

    try:
        settings, origins = merge_settings(
            RunSettings.model_validate(preset["settings"]) if preset else None,
            body.settings,
        )
    except Problem as error:
        raise LibraryError(422, error.diagnostic["code"], str(error)) from error
    for field in ("dataset_id", "profile_dataset_id"):
        if dataset_id(field) is not None:
            origins[field] = "override" if field in body.model_fields_set else "preset"
    return SelectedRun(
        dataset_id("dataset_id"),
        dataset_id("profile_dataset_id"),
        settings if preset or body.settings is not None else None,
        origins,
        {key: preset[key] for key in ("id", "name", "revision")} if preset else None,
    )
