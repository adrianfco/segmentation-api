from app.models import ApiKey, Base, Image, SegmentationJob, Team


def test_team_is_registered_on_the_shared_metadata():
    assert Team.__tablename__ == "teams"
    assert "teams" in Base.metadata.tables


def test_team_columns_are_as_expected():
    columns = Base.metadata.tables["teams"].columns

    assert {"id", "name", "slug", "created_at"} == set(columns.keys())
    assert columns["id"].primary_key
    assert columns["slug"].unique
    assert columns["created_at"].server_default is not None


def test_api_key_is_registered_on_the_shared_metadata():
    assert ApiKey.__tablename__ == "api_keys"
    assert "api_keys" in Base.metadata.tables


def test_api_key_columns_are_as_expected():
    table = Base.metadata.tables["api_keys"]
    columns = table.columns

    assert {"id", "team_id", "name", "key_hash", "created_at"} == set(columns.keys())
    assert columns["id"].primary_key
    assert columns["key_hash"].unique
    assert columns["created_at"].server_default is not None
    assert columns["team_id"].index
    team_fk = next(iter(columns["team_id"].foreign_keys))
    assert team_fk.column is Base.metadata.tables["teams"].c.id
    assert team_fk.ondelete == "CASCADE"


def test_image_is_registered_on_the_shared_metadata():
    assert Image.__tablename__ == "images"
    assert "images" in Base.metadata.tables


def test_image_columns_are_as_expected():
    columns = Base.metadata.tables["images"].columns

    assert {"id", "team_id", "storage_path", "content_type", "created_at"} == set(columns.keys())
    assert columns["id"].primary_key
    assert columns["created_at"].server_default is not None
    assert columns["team_id"].index
    team_fk = next(iter(columns["team_id"].foreign_keys))
    assert team_fk.column is Base.metadata.tables["teams"].c.id
    assert team_fk.ondelete == "CASCADE"


def test_segmentation_job_is_registered_on_the_shared_metadata():
    assert SegmentationJob.__tablename__ == "segmentation_jobs"
    assert "segmentation_jobs" in Base.metadata.tables


def test_segmentation_job_columns_are_as_expected():
    columns = Base.metadata.tables["segmentation_jobs"].columns

    assert {
        "id",
        "team_id",
        "image_id",
        "status",
        "result_path",
        "error_message",
        "created_at",
        "updated_at",
    } == set(columns.keys())
    assert columns["id"].primary_key
    assert columns["result_path"].nullable
    assert columns["error_message"].nullable
    assert columns["created_at"].server_default is not None
    assert columns["updated_at"].server_default is not None
    assert columns["image_id"].index

    teams, images = Base.metadata.tables["teams"], Base.metadata.tables["images"]
    team_fk = next(iter(columns["team_id"].foreign_keys))
    image_fk = next(iter(columns["image_id"].foreign_keys))
    assert team_fk.column is teams.c.id
    assert team_fk.ondelete == "CASCADE"
    assert image_fk.column is images.c.id
    assert image_fk.ondelete == "CASCADE"


def test_segmentation_job_has_composite_team_status_index():
    table = Base.metadata.tables["segmentation_jobs"]
    index_columns = {index.name: [c.name for c in index.columns] for index in table.indexes}

    assert index_columns["ix_segmentation_jobs_team_id_status"] == ["team_id", "status"]
