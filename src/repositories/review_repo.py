"""Repository for the ``health_reviews`` and ``ceo_reviews`` tables."""

from __future__ import annotations

import json
from typing import Any

import src.config
from src.database import get_db
from src.models.ceo_review import CeoReview, CeoReviewStatus


class HealthReviewRepository:
    """CRUD operations for health reviews."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or src.config.settings.db_path

    def insert(self, project_id: int, health_rating: str, review_json: str) -> int:
        with get_db(self._db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO health_reviews (project_id, health_rating, review_json) "
                "VALUES (?, ?, ?)",
                (project_id, health_rating, review_json),
            )
            conn.commit()
            return cursor.lastrowid

    def list_reviews(self, project_id: int, limit: int = 10) -> list[dict[str, Any]]:
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM health_reviews WHERE project_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        results = []
        for r in rows:
            review_data = json.loads(r["review_json"])
            review_data["id"] = r["id"]
            review_data["created_at"] = r["created_at"]
            review_data["health_rating"] = r["health_rating"]
            results.append(review_data)
        return results

    def get_review(self, review_id: int) -> dict[str, Any] | None:
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM health_reviews WHERE id = ?",
                (review_id,),
            ).fetchone()
        if not row:
            return None
        review_data = json.loads(row["review_json"])
        review_data["id"] = row["id"]
        review_data["created_at"] = row["created_at"]
        review_data["health_rating"] = row["health_rating"]
        return review_data


class CeoReviewRepository:
    """CRUD operations for CEO reviews."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or src.config.settings.db_path

    def insert(
        self, project_id: int, review_json: str, confluence_body: str, status: str,
    ) -> int:
        with get_db(self._db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO ceo_reviews (project_id, review_json, confluence_body, status) "
                "VALUES (?, ?, ?, ?)",
                (project_id, review_json, confluence_body, status),
            )
            conn.commit()
            return cursor.lastrowid

    def get_review(self, review_id: int) -> CeoReview | None:
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM ceo_reviews WHERE id = ?",
                (review_id,),
            ).fetchone()
        return CeoReview.from_row(row) if row else None

    def list_reviews(self, project_id: int, limit: int = 10) -> list[CeoReview]:
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM ceo_reviews WHERE project_id = ? ORDER BY id DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        return [CeoReview.from_row(r) for r in rows]

    def update_status(
        self, review_id: int, status: str, approval_item_id: int | None = None,
    ) -> None:
        with get_db(self._db_path) as conn:
            if approval_item_id is not None:
                conn.execute(
                    "UPDATE ceo_reviews SET status = ?, approval_item_id = ? WHERE id = ?",
                    (status, approval_item_id, review_id),
                )
            else:
                conn.execute(
                    "UPDATE ceo_reviews SET status = ? WHERE id = ?",
                    (status, review_id),
                )
            conn.commit()
