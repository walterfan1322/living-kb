from __future__ import annotations

from io import BytesIO
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader
from sqlalchemy.orm import Session

from living_kb.config import Settings
from living_kb.models import RawDocument, Source
from living_kb.utils import sha256_bytes, sha256_text, write_text


class IngestionService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def ingest_text(self, title: str, content: str, source_type: str, uri: str | None = None) -> RawDocument:
        source = Source(
            source_type=source_type,
            uri=uri,
            title=title,
            language="unknown",
            checksum=sha256_text(content),
        )
        self.session.add(source)
        self.session.flush()

        raw = RawDocument(source_id=source.id, content_text=content)
        self.session.add(raw)
        self.session.flush()

        snapshot_path = self.settings.raw_dir / f"raw_{raw.id}.txt"
        write_text(snapshot_path, content)
        raw.snapshot_path = str(snapshot_path)

        self.session.commit()
        self.session.refresh(raw)
        return raw

    def ingest_url(self, url: str) -> RawDocument:
        response = httpx.get(url, follow_redirects=True, timeout=30.0)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        title = soup.title.get_text(strip=True) if soup.title else url
        text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
        return self.ingest_text(title=title, content=text, source_type="url", uri=url)

    def ingest_pdf(self, filename: str, data: bytes) -> RawDocument:
        reader = PdfReader(BytesIO(data))
        extracted = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        text = extracted or f"[empty pdf extraction] {filename}"
        raw = self.ingest_text(title=filename, content=text, source_type="pdf")
        asset_path = self._write_binary_asset(filename, data, raw.id)
        raw.asset_path = str(asset_path)
        self.session.commit()
        self.session.refresh(raw)
        return raw

    def ingest_image(self, filename: str, data: bytes) -> RawDocument:
        transcript = self._try_ocr(data)
        text = transcript or f"[image stored for later OCR review] {filename}"
        raw = self.ingest_text(title=filename, content=text, source_type="image")
        asset_path = self._write_binary_asset(filename, data, raw.id)
        raw.asset_path = str(asset_path)
        self.session.commit()
        self.session.refresh(raw)
        return raw

    def ingest_plain_file(self, filename: str, data: bytes) -> RawDocument:
        text = data.decode("utf-8", errors="ignore")
        raw = self.ingest_text(title=filename, content=text, source_type="file")
        asset_path = self._write_binary_asset(filename, data, raw.id)
        raw.asset_path = str(asset_path)
        self.session.commit()
        self.session.refresh(raw)
        return raw

    def _write_binary_asset(self, filename: str, data: bytes, raw_id: int) -> Path:
        checksum = sha256_bytes(data)[:12]
        extension = Path(filename).suffix or ".bin"
        path = self.settings.artifacts_dir / f"raw_{raw_id}_{checksum}{extension}"
        path.write_bytes(data)
        return path

    def _try_ocr(self, data: bytes) -> str | None:
        try:
            from PIL import Image  # type: ignore
            import pytesseract  # type: ignore
        except ImportError:
            return None

        try:
            image = Image.open(BytesIO(data))
            text = pytesseract.image_to_string(image)
            return text.strip() or None
        except Exception:
            return None
