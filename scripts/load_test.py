import argparse
import asyncio
import csv
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

DEFAULT_IMAGE = Path(__file__).parent / "example.png"


def summarize(values: list[float]) -> dict[str, float]:
    q = statistics.quantiles(values, n=100, method="inclusive")
    return {"p50": q[49], "p95": q[94], "p99": q[98], "max": max(values)}


async def run_load_test(args: argparse.Namespace) -> dict:
    async with httpx.AsyncClient(
        base_url=args.base_url, headers={"X-API-Key": args.api_key}, timeout=30
    ) as client:
        with args.image.open("rb") as f:
            response = await client.post(
                "/v1/images", files={"file": (args.image.name, f, "image/png")}
            )
        image_id = response.raise_for_status().json()["id"]

        params = {"algorithm": args.algorithm, "k": args.k, "max_iters": args.max_iters}
        if args.algorithm == "pfcm":
            params |= {"m": 2.0, "eta": 2.0}

        semaphore = asyncio.Semaphore(args.concurrency)
        enqueue_ms = []
        rejected = 0

        async def submit() -> None:
            nonlocal rejected
            async with semaphore:
                start = time.perf_counter()
                try:
                    response = await client.post(
                        "/v1/jobs", json={"image_id": image_id, "params": params}
                    )
                    response.raise_for_status()
                except httpx.HTTPError:
                    rejected += 1
                    return
                enqueue_ms.append((time.perf_counter() - start) * 1000)

        start = time.perf_counter()
        await asyncio.gather(*(submit() for _ in range(args.jobs)))
        submit_seconds = time.perf_counter() - start
        print(f"Submitted {len(enqueue_ms)}/{args.jobs} jobs in {submit_seconds:.1f}s, waiting...")

        deadline = time.monotonic() + args.timeout
        while True:
            pending = 0
            for status in ("queued", "running"):
                response = await client.get(
                    "/v1/jobs", params={"image_id": image_id, "status": status, "limit": 1}
                )
                pending += response.raise_for_status().json()["total"]
            if pending == 0:
                break
            if time.monotonic() > deadline:
                raise SystemExit(f"Timed out after {args.timeout}s with {pending} jobs pending")
            await asyncio.sleep(1)

        jobs = []
        while len(jobs) < len(enqueue_ms):
            response = await client.get(
                "/v1/jobs", params={"image_id": image_id, "limit": 100, "offset": len(jobs)}
            )
            jobs += response.raise_for_status().json()["items"]

    succeeded = [job for job in jobs if job["status"] == "succeeded"]
    if len(succeeded) < 2:
        raise SystemExit(f"Only {len(succeeded)} jobs succeeded, nothing to measure")

    created = [datetime.fromisoformat(job["created_at"]) for job in succeeded]
    finished = [datetime.fromisoformat(job["updated_at"]) for job in succeeded]
    job_seconds = [(f - c).total_seconds() for c, f in zip(created, finished, strict=True)]

    return {
        "submitted": len(enqueue_ms),
        "rejected": rejected,
        "succeeded": len(succeeded),
        "failed": len(jobs) - len(succeeded),
        "enqueue_rps": len(enqueue_ms) / submit_seconds,
        "enqueue_ms": summarize(enqueue_ms),
        "job_s": summarize(job_seconds),
        "jobs_per_min": len(succeeded) / (max(finished) - min(created)).total_seconds() * 60,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("api_key", help="raw key from tools/create_api_key.py")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument("--jobs", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--algorithm", choices=["kmeans", "pfcm"], default="kmeans")
    parser.add_argument("--k", type=int, default=6)
    parser.add_argument("--max-iters", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--workers", type=int, help="worker count on the server, saved to the CSV")
    parser.add_argument("--csv", type=Path, help="append the results as one row")
    args = parser.parse_args()

    r = asyncio.run(run_load_test(args))
    enq, job = r["enqueue_ms"], r["job_s"]

    print(
        f"\njobs         {r['succeeded']} succeeded, {r['failed']} failed, "
        f"{r['rejected']} rejected by the API\n"
        f"enqueue      {r['enqueue_rps']:.1f} req/s   p50 {enq['p50']:.1f} ms   "
        f"p95 {enq['p95']:.1f} ms   p99 {enq['p99']:.1f} ms   max {enq['max']:.1f} ms\n"
        f"job latency  p50 {job['p50']:.2f} s   p95 {job['p95']:.2f} s   "
        f"p99 {job['p99']:.2f} s   max {job['max']:.2f} s\n"
        f"throughput   {r['jobs_per_min']:.1f} jobs/min"
    )

    if args.csv:
        row = {
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "workers": args.workers,
            "algorithm": args.algorithm,
            "k": args.k,
            "max_iters": args.max_iters,
            "jobs": args.jobs,
            "concurrency": args.concurrency,
            "succeeded": r["succeeded"],
            "failed": r["failed"],
            "rejected": r["rejected"],
            "enqueue_rps": round(r["enqueue_rps"], 1),
            **{f"enqueue_{k}_ms": round(v, 1) for k, v in enq.items()},
            **{f"job_{k}_s": round(v, 2) for k, v in job.items()},
            "jobs_per_min": round(r["jobs_per_min"], 1),
        }
        new_file = not args.csv.exists()
        with args.csv.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=row)
            if new_file:
                writer.writeheader()
            writer.writerow(row)


if __name__ == "__main__":
    main()
