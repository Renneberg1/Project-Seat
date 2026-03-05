"""Zoom transcript ingestion — fetch recordings, download transcripts, match, analyze."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import src.config
from src.config import Settings

logger = logging.getLogger(__name__)

# Throttle transcript-availability checks to avoid hitting rate limits.
_TRANSCRIPT_CHECK_BATCH = 10
_TRANSCRIPT_CHECK_DELAY = 0.5  # seconds between batches


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
                from_date = (date.today() - timedelta(days=30)).isoformat()

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

        while start <= end:
            chunk_end = min(start + timedelta(days=30), end)
            meetings = await zoom.list_recordings(
                user_id=self._settings.zoom.user_id,
                from_date=start.strftime("%Y-%m-%d"),
                to_date=chunk_end.strftime("%Y-%m-%d"),
            )
            all_meetings.extend(meetings)
            start = chunk_end + timedelta(days=1)

        return all_meetings

    # ------------------------------------------------------------------
    # Transcript-only meeting discovery
    # ------------------------------------------------------------------

    async def fetch_transcript_only_meetings(self) -> int:
        """Discover meetings with live transcripts but no cloud recording.

        Lists past meetings via the Meetings API, skips any already known,
        then probes each for a transcript via ``GET /meetings/{uuid}/transcript``.
        Meetings that have a transcript are inserted with ``discovery_source='transcript'``.

        Returns the number of new transcript-only recordings inserted.
        """
        from src.connectors.zoom import ZoomConnector

        zoom = ZoomConnector(self._settings.zoom, db_path=self._db_path)
        try:
            last_sync = self._repo.get_last_sync_time()
            if last_sync:
                from_date = last_sync[:10]
            else:
                from_date = (date.today() - timedelta(days=30)).isoformat()

            to_date = date.today().isoformat()

            logger.info(
                "Zoom transcript-only: scanning past meetings from %s to %s",
                from_date, to_date,
            )

            meetings = await self._fetch_past_meetings_with_date_splits(
                zoom, from_date, to_date,
            )

            logger.info(
                "Zoom transcript-only: %d past meetings returned by report API",
                len(meetings),
            )

            new_count = 0
            checked = 0
            skipped_known = 0
            skipped_no_transcript = 0
            for mtg in meetings:
                uuid = mtg.get("uuid", "")
                if not uuid:
                    continue

                # Skip already-known meetings (from recordings or prior transcript scan)
                if self._repo.get_by_uuid(uuid):
                    skipped_known += 1
                    continue

                # Rate-limit transcript checks
                if checked > 0 and checked % _TRANSCRIPT_CHECK_BATCH == 0:
                    await asyncio.sleep(_TRANSCRIPT_CHECK_DELAY)
                checked += 1

                transcript_meta = await zoom.get_meeting_transcript(uuid)
                if transcript_meta is None:
                    skipped_no_transcript += 1
                    continue  # No transcript for this meeting

                download_url = transcript_meta.get("download_url", "")

                self._repo.insert_recording(
                    zoom_meeting_uuid=uuid,
                    zoom_meeting_id=str(mtg.get("id", "")),
                    topic=mtg.get("topic", ""),
                    host_email=mtg.get("host_email", ""),
                    start_time=mtg.get("start_time", ""),
                    duration_minutes=mtg.get("duration", 0),
                    transcript_url=download_url,
                    raw_metadata=mtg,
                    discovery_source="transcript",
                )
                new_count += 1

            logger.info(
                "Zoom transcript-only: %d new, %d already known, %d no transcript, %d checked",
                new_count, skipped_known, skipped_no_transcript, checked,
            )
            return new_count

        finally:
            await zoom.close()

    async def _fetch_past_meetings_with_date_splits(
        self, zoom: Any, from_date: str, to_date: str,
    ) -> list[dict[str, Any]]:
        """Fetch past meetings, splitting into 30-day windows (Zoom API limit)."""
        from datetime import datetime

        start = datetime.fromisoformat(from_date)
        end = datetime.fromisoformat(to_date)
        all_meetings: list[dict[str, Any]] = []

        while start <= end:
            chunk_end = min(start + timedelta(days=30), end)
            meetings = await zoom.list_past_meetings(
                user_id=self._settings.zoom.user_id,
                from_date=start.strftime("%Y-%m-%d"),
                to_date=chunk_end.strftime("%Y-%m-%d"),
            )
            all_meetings.extend(meetings)
            start = chunk_end + timedelta(days=1)

        return all_meetings

    # ------------------------------------------------------------------
    # Manual meeting UUID lookup
    # ------------------------------------------------------------------

    async def fetch_meeting_by_uuid(self, meeting_id_or_uuid: str) -> int | None:
        """Fetch a single meeting's transcript by ID or UUID (manual lookup).

        Accepts either a numeric meeting ID (e.g. ``81263056250``) or
        an opaque UUID (e.g. ``abc123==``).  When a numeric ID is given
        and the direct transcript lookup returns 404, we look up the
        meeting's past instances to find the correct instance UUID.

        Returns the zoom_recordings row ID if a transcript was found,
        or None if the meeting has no transcript.
        """
        from src.connectors.zoom import ZoomConnector

        meeting_id_or_uuid = meeting_id_or_uuid.strip()

        # Already known?
        existing = self._repo.get_by_uuid(meeting_id_or_uuid)
        if existing:
            logger.info("Meeting %s already in DB (id=%d)", meeting_id_or_uuid, existing.id)
            return existing.id

        zoom = ZoomConnector(self._settings.zoom, db_path=self._db_path)
        try:
            # Try direct transcript lookup first
            transcript_meta = await zoom.get_meeting_transcript(meeting_id_or_uuid)

            # If 404 and input looks numeric, try looking up past instances
            # to find the correct instance UUID
            if transcript_meta is None and meeting_id_or_uuid.isdigit():
                logger.info(
                    "Direct transcript lookup failed for meeting ID %s, "
                    "trying past instances...", meeting_id_or_uuid,
                )
                instances = await zoom.get_past_meeting_instances(meeting_id_or_uuid)
                logger.info(
                    "Found %d past instances for meeting %s",
                    len(instances), meeting_id_or_uuid,
                )

                # Try each instance (most recent first) until we find one with a transcript
                for inst in reversed(instances):
                    inst_uuid = inst.get("uuid", "")
                    if not inst_uuid:
                        continue

                    # Check if this instance is already known
                    if self._repo.get_by_uuid(inst_uuid):
                        logger.info("Instance UUID %s already in DB", inst_uuid)
                        existing = self._repo.get_by_uuid(inst_uuid)
                        return existing.id if existing else None

                    logger.info("Trying transcript for instance UUID %s", inst_uuid)
                    transcript_meta = await zoom.get_meeting_transcript(inst_uuid)
                    if transcript_meta is not None:
                        # Use the instance UUID as the canonical identifier
                        meeting_id_or_uuid = inst_uuid
                        break

            if transcript_meta is None:
                logger.warning("No transcript found for meeting %s", meeting_id_or_uuid)
                return None

            download_url = transcript_meta.get("download_url", "")

            rec_id = self._repo.insert_recording(
                zoom_meeting_uuid=meeting_id_or_uuid,
                zoom_meeting_id=meeting_id_or_uuid,
                topic=transcript_meta.get("meeting_topic", "Manual lookup"),
                host_email="",
                start_time=transcript_meta.get("meeting_start_time", ""),
                duration_minutes=0,
                transcript_url=download_url,
                raw_metadata=transcript_meta,
                discovery_source="transcript",
            )
            logger.info("Inserted transcript-only meeting %s as id=%d", meeting_id_or_uuid, rec_id)
            return rec_id

        finally:
            await zoom.close()

    # ------------------------------------------------------------------
    # Download transcript for a recording
    # ------------------------------------------------------------------

    async def download_transcript(self, recording_id: int) -> bytes | None:
        """Download the VTT transcript for a recording. Returns raw bytes.

        For transcript-only recordings (``discovery_source='transcript'``),
        uses the meeting transcript endpoint rather than the recording download URL.
        """
        from src.connectors.zoom import ZoomConnector

        rec = self._repo.get_by_id(recording_id)
        if rec is None:
            return None

        if not rec.transcript_url:
            self._repo.update_status(recording_id, "failed", error_message="No transcript URL")
            return None

        zoom = ZoomConnector(self._settings.zoom, db_path=self._db_path)
        try:
            if rec.discovery_source == "transcript":
                vtt_bytes = await zoom.download_meeting_transcript(rec.transcript_url)
            else:
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

        stats = {"fetched": 0, "transcript_only": 0, "downloaded": 0, "matched": 0, "analyzed": 0, "errors": 0}

        # Step 1a: Fetch new recordings (cloud-recorded meetings)
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

        # Step 1b: Discover transcript-only meetings (no cloud recording)
        try:
            stats["transcript_only"] = await self.fetch_transcript_only_meetings()
        except Exception as exc:
            logger.warning("Zoom sync: transcript-only discovery failed: %s", exc)
            # Non-fatal — continue with whatever recordings we have

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
