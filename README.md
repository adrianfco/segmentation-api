# segmentation-api

Backend API service for asynchronous image segmentation.

Internal clients authenticate with team-scoped API keys, upload images, create
segmentation jobs, poll job status, and retrieve generated results. Jobs are
processed asynchronously by a background worker pool that runs
[segmentation-core](https://github.com/adrianfco/segmentation-core).

> Work in progress — documentation will grow with the project.
