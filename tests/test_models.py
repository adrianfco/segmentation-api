from app.models import Base, Team


def test_team_is_registered_on_the_shared_metadata():
    assert Team.__tablename__ == "teams"
    assert "teams" in Base.metadata.tables


def test_team_columns_are_as_expected():
    columns = Base.metadata.tables["teams"].columns

    assert {"id", "name", "slug", "created_at"} == set(columns.keys())
    assert columns["id"].primary_key
    assert columns["slug"].unique
    assert columns["created_at"].server_default is not None
