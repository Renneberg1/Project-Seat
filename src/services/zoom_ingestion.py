"""Zoom transcript ingestion — fetch recordings, download transcripts, match, analyze."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import src.config
from src.config import Settings

logger = logging.getLogger(__name__)


class ZoomIngestionService:
    """Orchestrates fetching Zoom recordings and processing transcripts."""

    def __init__(
        self,
        db_path: str | None = None,
        settings: Settings | None = None,
        zoom_repo: "ZoomRepository | None" = None,
    ) -> None:
        self._settings = settings or src.config.settings
        self._db_path = db_path or self._settings.db_path

        from src.repositories.zoom_repo import ZoomRepository
        self._repo = zoom_repo or ZoomRepository(self._db_path)

    # ------------------------------------------------------------------
    # Fetch new recordings from Zoom
    # ------------------------------------------------------------------

    async def fetch_new_recordings(self) -> int:
        """Fetch new recordings from Zoom since last sync.

        Returns the number of new recordings inserted.
        """
        from src.connectors.zoom import ZoomConnector

        zoom = ZoomConnector(self._settings.zoom, db_path=self._db_path)
        try:
            # Determine date range
            last_sync = self._repo.get_last_sync_time()
            if last_sync:
                from_date = last_sync[:10]  # YYYY-MM-DD
            else:
                from_date = (date.today() - timedelta(days=7)).isoformat()

            to_date = date.today().isoformat()

            logger.info("Zoom sync: fetching recordings from %s to %s", from_date, to_date)

            # Zoom API limits date range to 1 month — split if needed
            meetings = await self._fetch_with_date_splits(zoom, from_date, to_date)

            new_count = 0
            for meeting in meetings:
                uuid = meeting.get("uuid", "")
                if not uuid:
                    continue

                # Skip if already known
                if self._repo.get_by_uuid(uuid):
                    continue

                # Find transcript file in recording_files
                transcript_url = ""
                for rf in meeting.get("recording_files", []):
                    if rf.get("recording_type") == "audio_transcript" or (
                        rf.get("file_type", "").upper() == "TRANSCRIPT"
                    ):
                        transcript_url = rf.get("download_url", "")
                        break

                self._repo.insert_recording(
                    zoom_meeting_uuid=uuid,
                    zoom_meeting_id=str(meeting.get("id", "")),
                    topic=meeting.get("topic", ""),
                    host_email=meeting.get("host_email", ""),
                    start_time=meeting.get("start_time", ""),
                    duration_minutes=meeting.get("duration", 0),
                    transcript_url=transcript_url,
                    raw_metadata=meeting,
                )
                new_count += 1

            # Update last sync time
            self._repo.set_last_sync_time(to_date)
            logger.info("Zoom sync: %d new recordings found", new_count)
            return new_count

        finally:
            await zoom.close()

    async def _fetch_with_date_splits(
        self, zoom: Any, from_date: str, to_date: str,
    ) -> list[dict[str, Any]]:
        """Fetch recordings, splitting into 30-day windows if needed."""
        from datetime import datetime

        start = datetime.fromisoformat(from_date)
        end = datetime.fromisoformat(to_date)
        all_meetings: list[dict[str, Any]] = []

        while start < end:
            chunk_end = min(start + timedelta(days=30), end)
            meetings = await zoom.list_recordings(
                user_id=self._settings.zoom.user_id,
                from_date=start.strftime("%Y-%m-%d"),
                to_date=chunk_end.strftime("%Y-%m-%d"),
            )
            all_meetings.extend(meetings)
            start = chunk_end

        return all_meetings

    # ------------------------------------------------------------------
    # Download transcript for a recording
    # ------------------------------------------------------------------

    async def download_transcript(self, recording_id: int) -> bytes | None:
        """Download the VTT transcript for a recording. Returns raw bytes."""
        from src.connectors.zoom import ZoomConnector

        rec = self._repo.get_by_id(recording_id)
        if rec is None:
            return None

        if not rec.transcript_url:
            self._repo.update_status(recording_id, "failed", error_message="No transcript URL")
            return None

        zoom = ZoomConnector(self._settings.zoom, db_path=self._db_path)
        try:
            vtt_bytes = await zoom.download_transcript(rec.transcript_url)
            self._repo.update_status(recording_id, "downloaded")
            return vtt_bytes
        except Exception as exc:
            logger.error("Failed to download transcript for recording %d: %s", recording_id, exc)
            self._repo.update_status(recording_id, "failed", error_message=str(exc)[:500])
            return None
        finally:
            await zoom.close()

    # ------------------------------------------------------------------
    # Full sync cycle (called at startup + via Sync button)
    # ------------------------------------------------------------------

    async def run_full_sync(self) -> dict[str, int]:
        """Run the complete sync cycle: fetch → download → match → analyze.

        Returns a summary dict with counts.
        """
        from src.services.zoom_matching import ZoomMatchingService

        stats = {"fetched": 0, "downloaded": 0, "matched": 0, "analyzed": 0, "errors": 0}

        # Step 1: Fetch new recordings
        try:
            stats["fetched"] = await self.fetch_new_recordings()
        except Exception as exc:
            from src.connectors.zoom import ZoomNotAuthorizedError
            if isinstance(exc, ZoomNotAuthorizedError):
                logger.warning("Zoom sync skipped: %s", exc)
            else:
                logger.error("Zoom sync: fetch failed: %s", exc)
            stats["errors"] += 1
            return stats

        # Step 2: Process recordings that are new (have transcript URL)
        new_recordings = self._repo.list_by_status("new")
        matcher = ZoomMatchingService(db_path=self._db_path, settings=self._settings)

        for rec in new_recordings:
            try:
                # Download transcript
                if not rec.transcript_url:
                    self._repo.update_status(rec.id, "failed", error_message="No transcript URL")
                    stats["errors"] += 1
                    continue

                vtt_bytes = await self.download_transcript(rec.id)
                if vtt_bytes is None:
                    stats["errors"] += 1
                    continue
                stats["downloaded"] += 1

                # Parse transcript
                from src.services.transcript_parser import TranscriptParser
                parser = TranscriptParser()
                parsed = parser.parse(f"{rec.topic}.vtt", vtt_bytes)

                # Match to project(s)
                self._repo.update_status(rec.id, "matching")
                project_ids = await matcher.match_recording(rec, parsed.raw_text[:2000])

                if not project_ids:
                    self._repo.update_status(rec.id, "unmatched")
                    continue

                self._repo.update_status(
                    rec.id, "matched",
                    match_method=matcher.last_match_method,
                )
                stats["matched"] += 1

                # Analyze for each matched project
                from src.services.transcript import TranscriptService
                from src.services.dashboard import DashboardService

                ts = TranscriptService(db_path=self._db_path, settings=self._settings)
                dash = DashboardService(db_path=self._db_path, settings=self._settings)

                analysis_failed = False
                for pid in project_ids:
                    try:
                        project = dash.get_project_by_id(pid)
                        if project is None:
                            continue

                        # Store transcript for this project
                        tid = ts.store_transcript(pid, parsed, source="zoom")
                        self._repo.add_project_mapping(rec.id, pid, tid)

                        # Run LLM analysis
                        await ts.analyze_transcript(tid, project)
                        self._repo.update_mapping_transcript(rec.id, pid, tid)
                        stats["analyzed"] += 1

                    except Exception as exc:
                        logger.error(
                            "Zoom sync: analysis failed for recording %d, project %d: %s",
                            rec.id, pid, exc,
                        )
                        self._repo.update_mapping_status(rec.id, pid, "failed")
                        stats["errors"] += 1
                        analysis_failed = True

                if analysis_failed:
                    self._repo.update_status(rec.id, "failed", error_message="One or more project analyses failed")
                else:
                    self._repo.update_status(rec.id, "complete")

            except Exception as exc:
                logger.error("Zoom sync: processing failed for recording %d: %s", rec.id, exc)
                self._repo.update_status(rec.id, "failed", error_message=str(exc)[:500])
                stats["errors"] += 1

        logger.info("Zoom sync complete: %s", stats)
        return stats


async def run_zoom_sync() -> dict[str, int]:
    """Top-level convenience function for startup + manual trigger."""
    service = ZoomIngestionService()
    return await service.run_full_sync()
