"""Release service — scope-freeze, document selection, and publish tracking."""

from __future__ import annotations

import json
import logging

import src.config
from src.models.release import Release, ReleaseStatus

logger = logging.getLogger(__name__)


class ReleaseService:
    """Manage named releases with document scope-freeze and version snapshots."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or src.config.settings.db_path

        from src.repositories.release_repo import ReleaseRepository
        from src.repositories.approval_repo import ApprovalRepository
        self._repo = ReleaseRepository(self._db_path)
        self._audit_repo = ApprovalRepository(self._db_path)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_release(self, project_id: int, name: str) -> Release:
        return self._repo.create_release(project_id, name)

    def delete_release(self, release_id: int) -> None:
        self._repo.delete_release(release_id)

    def list_releases(self, project_id: int) -> list[Release]:
        return self._repo.list_releases(project_id)

    def get_release(self, release_id: int) -> Release | None:
        return self._repo.get_release(release_id)

    # ------------------------------------------------------------------
    # Document selection
    # ------------------------------------------------------------------

    def save_documents(self, release_id: int, titles: set[str]) -> None:
        self._repo.save_documents(release_id, titles)
        self._log_audit("save_release_documents", release_id, {
            "release_id": release_id, "count": len(titles),
        })

    def get_selected_documents(self, release_id: int) -> set[str]:
        return self._repo.get_selected_documents(release_id)

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
        self._repo.lock_release(release_id, snapshot_json)
        self._log_audit("lock_release", release_id, {
            "release_id": release_id, "snapshot": version_data,
        })

    def unlock_release(self, release_id: int) -> None:
        self._repo.unlock_release(release_id)
        self._log_audit("unlock_release", release_id, {"release_id": release_id})

    def get_version_snapshot(self, release_id: int) -> dict[str, str | None] | None:
        release = self.get_release(release_id)
        if release is None:
            return None
        return release.version_snapshot

    # ------------------------------------------------------------------
    # Audit trail
    # ------------------------------------------------------------------

    def _log_audit(self, action: str, release_id: int, details: dict) -> None:
        """Write a release action to the audit log for traceability."""
        project_id = self._repo.get_project_id(release_id)
        self._audit_repo.log_audit_raw(project_id, action, details)

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
