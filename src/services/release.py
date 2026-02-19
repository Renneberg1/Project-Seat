"""Release service — scope-freeze, document selection, and publish tracking."""

from __future__ import annotations

import json

import src.config
from src.database import get_db
from src.models.release import Release, ReleaseStatus


class ReleaseService:
    """Manage named releases with document scope-freeze and version snapshots."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or src.config.settings.db_path

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_release(self, project_id: int, name: str) -> Release:
        with get_db(self._db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO releases (project_id, name) VALUES (?, ?)",
                (project_id, name),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM releases WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return Release.from_row(row)

    def delete_release(self, release_id: int) -> None:
        with get_db(self._db_path) as conn:
            conn.execute("DELETE FROM release_documents WHERE release_id = ?", (release_id,))
            conn.execute("DELETE FROM releases WHERE id = ?", (release_id,))
            conn.commit()

    def list_releases(self, project_id: int) -> list[Release]:
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM releases WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return [Release.from_row(r) for r in rows]

    def get_release(self, release_id: int) -> Release | None:
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM releases WHERE id = ?", (release_id,)
            ).fetchone()
        return Release.from_row(row) if row else None

    # ------------------------------------------------------------------
    # Document selection
    # ------------------------------------------------------------------

    def save_documents(self, release_id: int, titles: set[str]) -> None:
        with get_db(self._db_path) as conn:
            conn.execute(
                "DELETE FROM release_documents WHERE release_id = ?", (release_id,)
            )
            for title in sorted(titles):
                conn.execute(
                    "INSERT INTO release_documents (release_id, doc_title) VALUES (?, ?)",
                    (release_id, title),
                )
            conn.commit()

    def get_selected_documents(self, release_id: int) -> set[str]:
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT doc_title FROM release_documents WHERE release_id = ?",
                (release_id,),
            ).fetchall()
        return {r["doc_title"] for r in rows}

    def reconcile_documents(
        self, release_id: int, current_titles: set[str]
    ) -> tuple[set[str], list[str]]:
        """Remove stale documents no longer in the DHF.

        Returns (valid_titles, stale_titles_removed).
        """
        selected = self.get_selected_documents(release_id)
        valid = selected & current_titles
        stale = sorted(selected - current_titles)
        if stale:
            self.save_documents(release_id, valid)
        return valid, stale

    # ------------------------------------------------------------------
    # Lock / unlock
    # ------------------------------------------------------------------

    def lock_release(self, release_id: int, version_data: dict[str, str | None]) -> None:
        snapshot_json = json.dumps(version_data)
        with get_db(self._db_path) as conn:
            conn.execute(
                "UPDATE releases SET locked = 1, version_snapshot = ? WHERE id = ?",
                (snapshot_json, release_id),
            )
            conn.commit()

    def unlock_release(self, release_id: int) -> None:
        with get_db(self._db_path) as conn:
            conn.execute(
                "UPDATE releases SET locked = 0 WHERE id = ?",
                (release_id,),
            )
            conn.commit()

    def get_version_snapshot(self, release_id: int) -> dict[str, str | None] | None:
        release = self.get_release(release_id)
        if release is None:
            return None
        return release.version_snapshot

    # ------------------------------------------------------------------
    # Release status computation
    # ------------------------------------------------------------------

    def compute_release_status(
        self,
        snapshot: dict[str, str | None],
        current_docs: dict[str, str | None],
        selected_docs: set[str] | None = None,
    ) -> list[tuple[str, ReleaseStatus]]:
        """Compare snapshot versions vs current released versions.

        Iterates over *selected_docs* (the source of truth for which
        documents belong to the release).  Falls back to snapshot keys
        when *selected_docs* is not provided.

        A document is PUBLISHED if its current released version differs from
        the snapshot (i.e., a new version was released since the freeze).
        Otherwise it is PENDING.
        """
        titles = selected_docs if selected_docs is not None else set(snapshot.keys())
        results: list[tuple[str, ReleaseStatus]] = []
        for title in sorted(titles):
            snapshot_version = snapshot.get(title)
            current_version = current_docs.get(title)
            if current_version is not None and current_version != snapshot_version:
                results.append((title, ReleaseStatus.PUBLISHED))
            else:
                results.append((title, ReleaseStatus.PENDING))
        return results
