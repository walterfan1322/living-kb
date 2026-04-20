from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import combinations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from living_kb.config import Settings
from living_kb.models import HealthFinding, KnowledgePage, PageLink
from living_kb.utils import jaccard_similarity, json_dumps, json_loads


NEGATION_MARKERS = {"not", "no", "never", "deprecated", "obsolete", "without"}


class HealthCheckService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def run(self) -> list[HealthFinding]:
        self.session.execute(delete(HealthFinding).where(HealthFinding.status == "open"))
        pages = list(self.session.scalars(select(KnowledgePage)).all())
        findings: list[HealthFinding] = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.settings.stale_days)

        for page in pages:
            updated_at = self._as_utc(page.updated_at)
            outgoing = len(
                list(self.session.scalars(select(PageLink).where(PageLink.from_page_id == page.id)).all())
            )
            incoming = len(
                list(self.session.scalars(select(PageLink).where(PageLink.to_page_id == page.id)).all())
            )
            if outgoing == 0 and incoming == 0:
                findings.append(
                    self._create_finding(
                        page.id,
                        "orphan_page",
                        "medium",
                        {"message": "Page has no graph connections"},
                    )
                )

            if updated_at and updated_at < cutoff:
                findings.append(
                    self._create_finding(
                        page.id,
                        "stale_page",
                        "medium",
                        {"message": f"Page has not been updated since {updated_at.isoformat()}"},
                    )
                )

            if len(page.summary.strip()) < 120:
                findings.append(
                    self._create_finding(
                        page.id,
                        "thin_page",
                        "low",
                        {"message": "Summary is short and may need expansion"},
                    )
                )

        for left, right in combinations(pages, 2):
            similarity = self._page_similarity(left, right)
            if similarity < 0.5:
                continue
            if self._has_negation_mismatch(left.summary, right.summary):
                findings.append(
                    self._create_finding(
                        left.id,
                        "contradiction_candidate",
                        "high",
                        {
                            "message": f"Potential contradiction with {right.slug}",
                            "related_page_id": right.id,
                            "confidence": round(similarity, 3),
                        },
                    )
                )

        self.session.commit()
        return findings

    def _page_similarity(self, left: KnowledgePage, right: KnowledgePage) -> float:
        left_tags = set(json_loads(left.tags_json, []))
        right_tags = set(json_loads(right.tags_json, []))
        return jaccard_similarity(left_tags, right_tags)

    def _has_negation_mismatch(self, left: str, right: str) -> bool:
        left_has = any(marker in left.lower().split() for marker in NEGATION_MARKERS)
        right_has = any(marker in right.lower().split() for marker in NEGATION_MARKERS)
        return left_has != right_has

    def _as_utc(self, value: datetime | None) -> datetime | None:
        if not value:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _create_finding(
        self, page_id: int | None, finding_type: str, severity: str, details: dict
    ) -> HealthFinding:
        finding = HealthFinding(
            page_id=page_id,
            finding_type=finding_type,
            severity=severity,
            details_json=json_dumps(details),
        )
        self.session.add(finding)
        self.session.flush()
        return finding
