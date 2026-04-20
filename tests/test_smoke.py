from uuid import uuid4

from fastapi.testclient import TestClient

from living_kb.main import app


def test_root() -> None:
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["database_backend"] in {"sqlite", "postgresql"}
    assert dashboard.json()["retrieval_mode"] in {"local-fallback", "hybrid"}
    assert dashboard.json()["embedding_provider"]
    assert dashboard.json()["llm_provider"] in {"none", "openai", "minimax"}
    app_response = client.get("/app")
    assert app_response.status_code == 200
    assert "Control Room" in app_response.text
    assert "Fetch URL" in app_response.text
    assert "Upload File" in app_response.text
    assert "Source Preview" in app_response.text
    assert "Activity And Lineage" in app_response.text


def test_ingest_compile_query_flow() -> None:
    client = TestClient(app)
    title = f"Living Knowledge Base {uuid4().hex[:8]}"

    ingest = client.post(
        "/api/ingest/text",
        json={
            "title": title,
            "content": (
                "A living knowledge base ingests raw sources, compiles them into markdown pages, "
                "builds graph links, and runs health checks to find contradictions and gaps."
            ),
            "source_type": "manual",
        },
    )
    assert ingest.status_code == 200
    raw_id = ingest.json()["raw_id"]

    compile_response = client.post(f"/api/compile/{raw_id}")
    assert compile_response.status_code == 200
    assert compile_response.json()["slug"].startswith("living-knowledge-base")

    query = client.post(
        "/api/query",
        json={"question": "How does a living knowledge base work?", "top_k": 3},
    )
    assert query.status_code == 200
    payload = query.json()
    assert payload["citations"]
    assert "knowledge base" in payload["answer"].lower()


def test_job_queue_and_review_flow() -> None:
    client = TestClient(app)
    title = f"Queued Page {uuid4().hex[:8]}"

    ingest = client.post(
        "/api/ingest/text",
        json={
            "title": title,
            "content": (
                "Queued compilation should create a pending review page after a job run. "
                "Health checks should surface findings that can be resolved from the review queue."
            ),
            "source_type": "manual",
        },
    )
    raw_id = ingest.json()["raw_id"]

    job = client.post(f"/api/jobs/compile/{raw_id}", json={})
    assert job.status_code == 200
    assert job.json()["status"] == "queued"
    job_id = job.json()["id"]

    run_once = client.post(f"/api/jobs/{job_id}/run")
    assert run_once.status_code == 200
    assert run_once.json()["status"] == "completed"

    jobs = client.get("/api/jobs")
    assert jobs.status_code == 200
    assert jobs.json()

    review_queue = client.get("/api/review-queue")
    assert review_queue.status_code == 200
    page_items = [item for item in review_queue.json() if item["item_type"] == "page"]
    assert page_items

    approved = client.post(f"/api/review/pages/{page_items[0]['id']}/approve", json={"notes": "Looks good"})
    assert approved.status_code == 200
    assert approved.json()["review_status"] == "approved"

    health_job = client.post("/api/jobs/health-check", json={})
    assert health_job.status_code == 200
    health_job_id = health_job.json()["id"]
    health_run = client.post(f"/api/jobs/{health_job_id}/run")
    assert health_run.status_code == 200
    assert health_run.json()["status"] == "completed"

    review_queue = client.get("/api/review-queue")
    finding_items = [item for item in review_queue.json() if item["item_type"] == "finding"]
    assert finding_items

    resolved = client.post(
        f"/api/review/findings/{finding_items[0]['id']}/resolve",
        json={"notes": "Reviewed and accepted"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"


def test_listing_endpoints() -> None:
    client = TestClient(app)
    raws = client.get("/api/raw-documents")
    pages = client.get("/api/pages")
    jobs = client.get("/api/jobs")
    assert raws.status_code == 200
    assert pages.status_code == 200
    assert jobs.status_code == 200


def test_file_ingest_endpoint() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/ingest/file",
        data={"source_type": "file"},
        files={"file": ("notes.txt", b"file upload content for living kb", "text/plain")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "notes.txt"
    assert payload["raw_id"] > 0
    detail = client.get(f"/api/raw-documents/{payload['raw_id']}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert "file upload content" in detail_payload["content_preview"]
    assert detail_payload["checksum"]
    assert detail_payload["parser_version"] == "mvp-v1"
    assert detail_payload["linked_page_slug"] is None


def test_page_revisions_and_diff() -> None:
    client = TestClient(app)
    title = f"Revision Page {uuid4().hex[:8]}"

    first = client.post(
        "/api/ingest/text",
        json={
            "title": title,
            "content": "Version one explains the original architecture with a raw layer and a compile layer.",
            "source_type": "manual",
        },
    ).json()
    client.post(f"/api/compile/{first['raw_id']}")

    second = client.post(
        "/api/ingest/text",
        json={
            "title": title,
            "content": "Version two adds a review queue, background jobs, and a page diff viewer for revision tracking.",
            "source_type": "manual",
        },
    ).json()
    compiled = client.post(f"/api/compile/{second['raw_id']}")
    assert compiled.status_code == 200

    slug = compiled.json()["slug"]
    raw_detail = client.get(f"/api/raw-documents/{second['raw_id']}")
    assert raw_detail.status_code == 200
    assert raw_detail.json()["linked_page_slug"] == slug
    revisions = client.get(f"/api/pages/{slug}/revisions")
    assert revisions.status_code == 200
    revision_items = revisions.json()
    assert len(revision_items) >= 2

    diff = client.get(f"/api/pages/{slug}/diff")
    assert diff.status_code == 200
    assert "Version two" in diff.json()["diff"] or "review queue" in diff.json()["diff"]


def test_audit_and_lineage_endpoints() -> None:
    client = TestClient(app)
    title = f"Audit Page {uuid4().hex[:8]}"

    raw = client.post(
        "/api/ingest/text",
        json={
            "title": title,
            "content": "This page is used to verify compile runs, review events, query events, and lineage APIs.",
            "source_type": "manual",
        },
    ).json()
    compiled = client.post(f"/api/compile/{raw['raw_id']}")
    assert compiled.status_code == 200
    slug = compiled.json()["slug"]

    compile_runs = client.get(f"/api/compile-runs?page_slug={slug}")
    assert compile_runs.status_code == 200
    assert compile_runs.json()
    assert compile_runs.json()[0]["status"] == "completed"

    approved = client.post(
        f"/api/review/pages/{compiled.json()['page_id']}/approve",
        json={"notes": "Audit approval"},
    )
    assert approved.status_code == 200

    review_events = client.get(f"/api/review-events?page_slug={slug}")
    assert review_events.status_code == 200
    assert any(event["action"] == "approve" for event in review_events.json())

    query = client.post(
        "/api/query",
        json={"question": f"What is {title} used for?", "top_k": 5},
    )
    assert query.status_code == 200

    query_events = client.get(f"/api/query-events?page_slug={slug}")
    assert query_events.status_code == 200
    assert query_events.json()

    lineage = client.get(f"/api/pages/{slug}/lineage")
    assert lineage.status_code == 200
    lineage_payload = lineage.json()
    assert lineage_payload["compile_runs"]
    assert lineage_payload["review_events"]
    assert lineage_payload["recent_queries"]
