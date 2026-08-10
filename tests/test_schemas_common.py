import pytest
from pydantic import ValidationError

from app.schemas.common import Page, PaginationParams, SignedUrlResponse
from app.schemas.health import HealthResponse


def test_page_validates_its_element_type():
    page = Page[HealthResponse](items=[{"status": "ok"}], total=1, limit=50, offset=0)

    assert page.items == [HealthResponse(status="ok")]

    with pytest.raises(ValidationError):
        Page[HealthResponse](items=[{"unexpected": "shape"}], total=1, limit=50, offset=0)


def test_pagination_defaults_apply_when_query_params_absent():
    params = PaginationParams()

    assert params.limit == 50
    assert params.offset == 0


@pytest.mark.parametrize("value", [0, 101])
def test_pagination_limit_must_be_within_bounds(value):
    with pytest.raises(ValidationError):
        PaginationParams(limit=value)


@pytest.mark.parametrize("value", [-1])
def test_pagination_offset_must_not_be_negative(value):
    with pytest.raises(ValidationError):
        PaginationParams(offset=value)


def test_signed_url_response_rejects_a_malformed_url():
    with pytest.raises(ValidationError):
        SignedUrlResponse(url="not-a-url", expires_at="2026-08-10T12:00:00Z")


def test_signed_url_response_serializes_to_json_primitives():
    response = SignedUrlResponse(
        url="https://example.supabase.co/object/sign/segmentation/img?token=abc",
        expires_at="2026-08-10T12:00:00Z",
    )
    dumped = response.model_dump(mode="json")

    assert dumped["url"] == "https://example.supabase.co/object/sign/segmentation/img?token=abc"
    assert dumped["expires_at"] == "2026-08-10T12:00:00Z"
