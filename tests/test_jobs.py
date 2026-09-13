import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import get_session
from app.main import create_app
from app.models import Image, JobStatus, SegmentationJob, Team
from app.schemas.common import SignedUrlResponse
from app.security import get_current_team
from app.storage import StorageError, get_storage


def make_client(session, team=None, storage=None):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:pw@localhost:5432/postgres",
        supabase_url="https://example.supabase.co/",
        supabase_service_role_key="service-role-key",
    )
    if team is not None:
        app.dependency_overrides[get_current_team] = lambda: team
    if storage is not None:
        app.dependency_overrides[get_storage] = lambda: storage
    return TestClient(app)


def stamp_server_defaults(job):
    job.created_at = datetime.now(UTC)
    job.updated_at = datetime.now(UTC)


def make_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.refresh.side_effect = stamp_server_defaults
    return session


def make_team():
    return Team(id=uuid.uuid4(), name="Acme")


def make_image(team):
    image_id = uuid.uuid4()
    return Image(
        id=image_id,
        team_id=team.id,
        filename="cat.png",
        storage_path=f"{team.id}/images/{image_id}.png",
        created_at=datetime.now(UTC),
    )


def make_body(image_id, **params):
    return {"image_id": str(image_id), "params": params}


def make_job(team, image, status=JobStatus.queued):
    job_id = uuid.uuid4()
    return SegmentationJob(
        id=job_id,
        team_id=team.id,
        image_id=image.id,
        status=status,
        params={"algorithm": "kmeans", "k": 4, "max_iters": 100, "seed": 42},
        result_path=f"{team.id}/results/{job_id}.png",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_create_job_returns_202():
    team, session = make_team(), make_session()
    image = make_image(team)
    session.scalar.return_value = image

    with make_client(session, team) as client:
        response = client.post(
            "/v1/jobs", json=make_body(image.id, algorithm="kmeans", k=4, max_iters=100, seed=42)
        )

    assert response.status_code == 202
    body = response.json()
    assert set(body) == {
        "id",
        "image_id",
        "status",
        "params",
        "error_message",
        "created_at",
        "updated_at",
    }
    assert body["status"] == "queued"
    assert body["image_id"] == str(image.id)
    assert body["error_message"] is None
    assert body["params"] == {"algorithm": "kmeans", "k": 4, "max_iters": 100, "seed": 42}

    [job] = session.add.call_args.args
    assert isinstance(job, SegmentationJob)
    assert str(job.id) == body["id"]
    assert job.team_id == team.id
    assert job.image_id == image.id
    assert job.status is JobStatus.queued
    assert job.params == body["params"]
    session.commit.assert_awaited_once()
    assert response.headers["location"] == f"http://testserver/v1/jobs/{body['id']}"


def test_create_job_scopes_image_lookup_to_team():
    team, session = make_team(), make_session()
    image = make_image(team)
    session.scalar.return_value = image

    with make_client(session, team) as client:
        response = client.post(
            "/v1/jobs", json=make_body(image.id, algorithm="kmeans", k=4, max_iters=100)
        )

    assert response.status_code == 202
    params = session.scalar.call_args.args[0].compile().params.values()
    assert image.id in params
    assert team.id in params


def test_create_job_stores_pfcm_params():
    team, session = make_team(), make_session()
    image = make_image(team)
    session.scalar.return_value = image

    with make_client(session, team) as client:
        response = client.post(
            "/v1/jobs",
            json=make_body(image.id, algorithm="pfcm", k=3, max_iters=50, seed=7, m=2.0, eta=2.5),
        )

    assert response.status_code == 202
    [job] = session.add.call_args.args
    assert job.params == {
        "algorithm": "pfcm",
        "k": 3,
        "max_iters": 50,
        "seed": 7,
        "m": 2.0,
        "eta": 2.5,
    }
    assert response.json()["params"] == job.params


def test_create_job_generates_seed_when_omitted():
    team, session = make_team(), make_session()
    image = make_image(team)
    session.scalar.return_value = image

    with make_client(session, team) as client:
        response = client.post(
            "/v1/jobs", json=make_body(image.id, algorithm="kmeans", k=4, max_iters=100)
        )

    assert response.status_code == 202
    seed = response.json()["params"]["seed"]
    assert isinstance(seed, int)
    assert 0 <= seed < 2**32

    [job] = session.add.call_args.args
    assert job.params["seed"] == seed


def test_create_job_image_not_found_returns_404():
    session = make_session()
    session.scalar.return_value = None

    with make_client(session, make_team()) as client:
        response = client.post(
            "/v1/jobs", json=make_body(uuid.uuid4(), algorithm="kmeans", k=4, max_iters=100)
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Image not found"}
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


def test_create_job_without_api_key_returns_401():
    session = make_session()

    with make_client(session) as client:
        response = client.post(
            "/v1/jobs", json=make_body(uuid.uuid4(), algorithm="kmeans", k=4, max_iters=100)
        )

    assert response.status_code == 401
    session.add.assert_not_called()


def test_create_job_pfcm_without_m_and_eta_returns_422():
    session = make_session()

    with make_client(session, make_team()) as client:
        response = client.post(
            "/v1/jobs", json=make_body(uuid.uuid4(), algorithm="pfcm", k=3, max_iters=50)
        )

    assert response.status_code == 422
    session.scalar.assert_not_awaited()
    session.add.assert_not_called()


def test_create_job_pfcm_without_eta_returns_422():
    with make_client(make_session(), make_team()) as client:
        response = client.post(
            "/v1/jobs", json=make_body(uuid.uuid4(), algorithm="pfcm", k=3, max_iters=50, m=2.0)
        )

    assert response.status_code == 422


def test_create_job_kmeans_with_pfcm_params_returns_422():
    session = make_session()

    with make_client(session, make_team()) as client:
        response = client.post(
            "/v1/jobs",
            json=make_body(uuid.uuid4(), algorithm="kmeans", k=4, max_iters=100, m=2.0, eta=2.5),
        )

    assert response.status_code == 422
    session.add.assert_not_called()


@pytest.mark.parametrize(
    "params",
    [
        {"algorithm": "dbscan", "k": 4, "max_iters": 100},
        {"k": 4, "max_iters": 100},
        {"algorithm": "kmeans", "k": 1, "max_iters": 100},
        {"algorithm": "kmeans", "k": 17, "max_iters": 100},
        {"algorithm": "kmeans", "k": 4, "max_iters": 0},
        {"algorithm": "kmeans", "k": 4, "max_iters": 1001},
        {"algorithm": "kmeans", "k": 4},
        {"algorithm": "kmeans", "k": 4, "max_iters": 100, "seed": -1},
        {"algorithm": "pfcm", "k": 3, "max_iters": 50, "m": 1.0, "eta": 2.5},
        {"algorithm": "pfcm", "k": 3, "max_iters": 50, "m": 2.0, "eta": 1.0},
        {"algorithm": "kmeans", "k": 4, "max_iters": 100, "pfcm_m": 2.0},
    ],
)
def test_create_job_invalid_params_returns_422(params):
    session = make_session()

    with make_client(session, make_team()) as client:
        response = client.post("/v1/jobs", json={"image_id": str(uuid.uuid4()), "params": params})

    assert response.status_code == 422
    session.add.assert_not_called()


def test_create_job_without_params_returns_422():
    with make_client(make_session(), make_team()) as client:
        response = client.post("/v1/jobs", json={"image_id": str(uuid.uuid4())})

    assert response.status_code == 422


def test_create_job_invalid_image_id_returns_422():
    params = {"algorithm": "kmeans", "k": 4, "max_iters": 100}

    with make_client(make_session(), make_team()) as client:
        response = client.post("/v1/jobs", json={"image_id": "not-a-uuid", "params": params})

    assert response.status_code == 422


def test_list_jobs_returns_page():
    team, session = make_team(), make_session()
    image = make_image(team)
    jobs = [make_job(team, image), make_job(team, image, JobStatus.succeeded)]
    session.scalar.return_value = 2
    session.scalars.return_value = MagicMock(all=MagicMock(return_value=jobs))

    with make_client(session, team) as client:
        response = client.get("/v1/jobs", params={"limit": 10, "offset": 5})

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [str(job.id) for job in jobs]
    assert [item["status"] for item in body["items"]] == ["queued", "succeeded"]
    assert (body["total"], body["limit"], body["offset"]) == (2, 10, 5)

    stmt = session.scalars.call_args.args[0]
    assert team.id in stmt.compile().params.values()


def test_list_jobs_filters_by_status_and_image_id():
    team, session = make_team(), make_session()
    image = make_image(team)
    session.scalar.return_value = 0
    session.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))

    with make_client(session, team) as client:
        response = client.get("/v1/jobs", params={"status": "running", "image_id": str(image.id)})

    assert response.status_code == 200
    for call in (session.scalar, session.scalars):
        params = call.call_args.args[0].compile().params.values()
        assert team.id in params
        assert JobStatus.running in params
        assert image.id in params


def test_list_jobs_unknown_status_returns_422():
    with make_client(make_session(), make_team()) as client:
        response = client.get("/v1/jobs", params={"status": "pending"})

    assert response.status_code == 422


def test_list_jobs_limit_out_of_range_returns_422():
    with make_client(make_session(), make_team()) as client:
        response = client.get("/v1/jobs", params={"limit": 101})

    assert response.status_code == 422


def test_get_job_returns_200():
    team, session = make_team(), make_session()
    job = make_job(team, make_image(team))
    session.scalar.return_value = job

    with make_client(session, team) as client:
        response = client.get(f"/v1/jobs/{job.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(job.id)
    assert body["status"] == "queued"
    assert body["params"] == job.params

    params = session.scalar.call_args.args[0].compile().params.values()
    assert job.id in params
    assert team.id in params


def test_get_job_not_found_returns_404():
    session = make_session()
    session.scalar.return_value = None

    with make_client(session, make_team()) as client:
        response = client.get(f"/v1/jobs/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Job not found"}


def test_get_job_invalid_id_returns_422():
    with make_client(make_session(), make_team()) as client:
        response = client.get("/v1/jobs/not-a-uuid")

    assert response.status_code == 422


def test_get_job_without_api_key_returns_401():
    with make_client(make_session()) as client:
        response = client.get(f"/v1/jobs/{uuid.uuid4()}")

    assert response.status_code == 401


def test_job_result_url_returns_signed_url():
    team, session, storage = make_team(), make_session(), AsyncMock()
    job = make_job(team, make_image(team), JobStatus.succeeded)
    session.scalar.return_value = job
    storage.create_signed_url.return_value = SignedUrlResponse(
        url="https://example.supabase.co/storage/v1/object/sign/result.png?token=abc",
        expires_at=datetime.now(UTC),
    )

    with make_client(session, team, storage) as client:
        response = client.get(f"/v1/jobs/{job.id}/result-url")

    assert response.status_code == 200
    assert response.json()["url"].endswith("result.png?token=abc")
    storage.create_signed_url.assert_awaited_once_with(job.result_path, 600)

    params = session.scalar.call_args.args[0].compile().params.values()
    assert job.id in params
    assert team.id in params


@pytest.mark.parametrize("job_status", [JobStatus.queued, JobStatus.running, JobStatus.failed])
def test_job_result_url_unfinished_returns_409(job_status):
    team, session, storage = make_team(), make_session(), AsyncMock()
    job = make_job(team, make_image(team), job_status)
    session.scalar.return_value = job

    with make_client(session, team, storage) as client:
        response = client.get(f"/v1/jobs/{job.id}/result-url")

    assert response.status_code == 409
    assert response.json() == {"detail": f"Job status is {job_status}"}
    storage.create_signed_url.assert_not_awaited()


def test_job_result_url_not_found_returns_404():
    session, storage = make_session(), AsyncMock()
    session.scalar.return_value = None

    with make_client(session, make_team(), storage) as client:
        response = client.get(f"/v1/jobs/{uuid.uuid4()}/result-url")

    assert response.status_code == 404
    assert response.json() == {"detail": "Job not found"}
    storage.create_signed_url.assert_not_awaited()


def test_job_result_url_storage_failure_returns_502():
    team, session, storage = make_team(), make_session(), AsyncMock()
    job = make_job(team, make_image(team), JobStatus.succeeded)
    session.scalar.return_value = job
    storage.create_signed_url.side_effect = StorageError("Storage returned 500", 500)

    with make_client(session, team, storage) as client:
        response = client.get(f"/v1/jobs/{job.id}/result-url")

    assert response.status_code == 502
    assert response.json() == {"detail": "Storage unavailable"}


def test_job_result_url_invalid_id_returns_422():
    with make_client(make_session(), make_team(), AsyncMock()) as client:
        response = client.get("/v1/jobs/not-a-uuid/result-url")

    assert response.status_code == 422


def test_job_result_url_without_api_key_returns_401():
    session, storage = make_session(), AsyncMock()

    with make_client(session, storage=storage) as client:
        response = client.get(f"/v1/jobs/{uuid.uuid4()}/result-url")

    assert response.status_code == 401
    storage.create_signed_url.assert_not_awaited()
