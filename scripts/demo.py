import argparse
import json
import time
from pathlib import Path

import httpx

DEFAULT_IMAGE = Path(__file__).parent / "example.png"
POLL_INTERVAL_SECONDS = 1
POLL_TIMEOUT_SECONDS = 60


def request(client: httpx.Client, method: str, path: str, **kwargs) -> httpx.Response:
    if "json" in kwargs:
        summary = json.dumps(kwargs["json"])
    elif "files" in kwargs:
        filename, _, content_type = kwargs["files"]["file"]
        summary = f"file={filename} ({content_type})"
    else:
        summary = ""
    print(f"> {method} {path}" + (f" {summary}" if summary else ""))

    response = client.request(method, path, **kwargs)
    print(f"< {response.status_code} {response.text}\n")

    if response.is_error:
        raise SystemExit(f"{method} {path} failed with {response.status_code}")
    return response


def run_demo(base_url: str, api_key: str, image_path: Path) -> None:
    client = httpx.Client(base_url=base_url, headers={"X-API-Key": api_key})

    with image_path.open("rb") as f:
        image = request(
            client, "POST", "/v1/images", files={"file": (image_path.name, f, "image/png")}
        ).json()

    params = {"algorithm": "kmeans", "k": 6, "max_iters": 50}
    job = request(
        client, "POST", "/v1/jobs", json={"image_id": image["id"], "params": params}
    ).json()
    job_id = job["id"]

    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while job["status"] in ("queued", "running"):
        if time.monotonic() > deadline:
            raise SystemExit(f"Timed out waiting for job {job_id} after {POLL_TIMEOUT_SECONDS}s")
        time.sleep(POLL_INTERVAL_SECONDS)
        job = request(client, "GET", f"/v1/jobs/{job_id}").json()

    if job["status"] != "succeeded":
        raise SystemExit(f"Job {job_id} failed: {job['error_message']}")

    result_url = request(client, "GET", f"/v1/jobs/{job_id}/result-url").json()["url"]
    result_bytes = httpx.get(result_url).raise_for_status().content

    output_path = Path("./scripts/segmented-example.png")
    output_path.write_bytes(result_bytes)
    print(f"Downloaded {len(result_bytes)} bytes -> {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("api_key", help="raw key from tools/create_api_key.py")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    args = parser.parse_args()

    run_demo(args.base_url, args.api_key, args.image)


if __name__ == "__main__":
    main()
