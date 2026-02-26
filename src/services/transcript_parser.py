"""Transcript file-format parsers — VTT, TXT, DOCX."""

from __future__ import annotations

import re
from io import BytesIO

from src.models.transcript import ParsedTranscript, TranscriptSegment


class TranscriptParser:
    """Parse meeting transcripts from various file formats."""

    def parse(self, filename: str, content: bytes) -> ParsedTranscript:
        """Route to the appropriate parser based on file extension."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext == "vtt":
            return self._parse_vtt(filename, content)
        elif ext == "txt":
            return self._parse_txt(filename, content)
        elif ext == "docx":
            return self._parse_docx(filename, content)
        else:
            raise ValueError(f"Unsupported file format: .{ext}. Use .vtt, .txt, or .docx")

    def _parse_vtt(self, filename: str, content: bytes) -> ParsedTranscript:
        """Parse WebVTT with <v Name> speaker tags and timestamp blocks."""
        text = content.decode("utf-8-sig", errors="replace")
        segments: list[TranscriptSegment] = []
        speakers: set[str] = set()

        # Split into blocks separated by blank lines
        blocks = re.split(r"\n\s*\n", text)
        timestamp_re = re.compile(
            r"(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})"
        )
        speaker_re = re.compile(r"<v\s+([^>]+)>(.+?)(?:</v>|$)", re.DOTALL)

        for block in blocks:
            lines = block.strip().split("\n")
            if not lines:
                continue

            ts_start = ts_end = None
            speech_lines: list[str] = []

            for line in lines:
                ts_match = timestamp_re.search(line)
                if ts_match:
                    ts_start, ts_end = ts_match.group(1), ts_match.group(2)
                    continue
                # Skip WEBVTT header and sequence numbers
                if line.strip().startswith("WEBVTT") or line.strip().isdigit():
                    continue
                if line.strip():
                    speech_lines.append(line.strip())

            if not speech_lines:
                continue

            full_text = " ".join(speech_lines)

            # Try to extract speaker from <v Name> tags
            speaker_match = speaker_re.search(full_text)
            if speaker_match:
                speaker = speaker_match.group(1).strip()
                spoken = speaker_re.sub(r"\2", full_text).strip()
            else:
                speaker = "Unknown"
                spoken = full_text

            speakers.add(speaker)
            segments.append(TranscriptSegment(
                speaker=speaker,
                text=spoken,
                timestamp_start=ts_start,
                timestamp_end=ts_end,
            ))

        raw = "\n".join(f"{s.speaker}: {s.text}" for s in segments)
        duration = None
        if segments and segments[-1].timestamp_end:
            duration = segments[-1].timestamp_end

        return ParsedTranscript(
            filename=filename,
            segments=segments,
            raw_text=raw,
            speaker_list=sorted(speakers),
            duration_hint=duration,
        )

    def _parse_txt(self, filename: str, content: bytes) -> ParsedTranscript:
        """Parse plain text with 'Name: text' speaker prefixes."""
        text = content.decode("utf-8-sig", errors="replace")
        segments: list[TranscriptSegment] = []
        speakers: set[str] = set()

        speaker_line_re = re.compile(r"^([A-Za-z][A-Za-z .'-]{0,40}):\s+(.+)$")

        current_speaker = "Unknown"
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            match = speaker_line_re.match(line)
            if match:
                current_speaker = match.group(1).strip()
                spoken = match.group(2).strip()
            else:
                spoken = line

            speakers.add(current_speaker)
            segments.append(TranscriptSegment(speaker=current_speaker, text=spoken))

        raw = "\n".join(f"{s.speaker}: {s.text}" for s in segments)
        return ParsedTranscript(
            filename=filename,
            segments=segments,
            raw_text=raw,
            speaker_list=sorted(speakers),
        )

    def _parse_docx(self, filename: str, content: bytes) -> ParsedTranscript:
        """Extract paragraph text via python-docx."""
        try:
            from docx import Document
        except ImportError:
            raise ImportError(
                "python-docx is required for .docx parsing. "
                "Install with: uv add python-docx"
            )

        doc = Document(BytesIO(content))
        segments: list[TranscriptSegment] = []
        speakers: set[str] = set()

        speaker_line_re = re.compile(r"^([A-Za-z][A-Za-z .'-]{0,40}):\s+(.+)$")
        current_speaker = "Unknown"

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            match = speaker_line_re.match(text)
            if match:
                current_speaker = match.group(1).strip()
                spoken = match.group(2).strip()
            else:
                spoken = text

            speakers.add(current_speaker)
            segments.append(TranscriptSegment(speaker=current_speaker, text=spoken))

        raw = "\n".join(f"{s.speaker}: {s.text}" for s in segments)
        return ParsedTranscript(
            filename=filename,
            segments=segments,
            raw_text=raw,
            speaker_list=sorted(speakers),
        )
