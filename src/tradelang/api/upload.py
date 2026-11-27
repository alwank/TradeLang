"""Bounded multipart streaming into a private import directory."""

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Request
from python_multipart import MultipartParser
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from ..persistence import LibraryError
from .limits import reject_non_json_number

if TYPE_CHECKING:
    from python_multipart.multipart import MultipartCallbacks

MAX_FILE = 100 * 1024**2
MAX_METADATA = 2 * 1024**2
MAX_FRAMING = 16 * 1024
TOTAL_SECONDS = 120
INACTIVITY_SECONDS = 30


def malformed():
    return LibraryError(
        400, "E_MULTIPART", "Expected one file and one JSON metadata part"
    )


def too_large():
    return LibraryError(413, "E_REQUEST_SIZE", "Import exceeds the upload size limit")


async def receive_upload(request: Request, stage: Path):
    content_type, parameters = parse_options_header(
        request.headers.get("content-type", "")
    )
    if content_type != b"multipart/form-data":
        raise LibraryError(415, "E_CONTENT_TYPE", "Expected multipart/form-data")
    boundary = parameters.get(b"boundary", b"")
    if not boundary or len(boundary) > 70:
        raise malformed()
    headers: dict[bytes, bytes] = {}
    key = bytearray()
    value = bytearray()
    metadata = bytearray()
    fields: set[bytes] = set()
    field = None
    filename = ""
    file_size = 0
    completed = False
    raw = stage / "upload"

    def begin():
        headers.clear()

    def end_header():
        header = bytes(key).lower()
        if header in headers:
            raise malformed()
        headers[header] = bytes(value)
        key.clear()
        value.clear()

    def end_headers():
        nonlocal field, filename
        disposition, params = parse_options_header(
            headers.get(b"content-disposition", b"")
        )
        field = params.get(b"name")
        if (
            disposition != b"form-data"
            or field not in (b"file", b"metadata")
            or field in fields
        ):
            raise malformed()
        fields.add(field)
        if field == b"file":
            try:
                candidate = (
                    params[b"filename"]
                    .decode("utf-8")
                    .replace("\\", "/")
                    .rsplit("/", 1)[-1]
                )
            except (KeyError, UnicodeError) as exc:
                raise malformed() from exc
            filename = "".join(c for c in candidate if c.isprintable())
            if not filename or len(filename.encode()) > 255:
                raise malformed()

    def end():
        nonlocal completed
        completed = True

    def append_header(target, data, start, stop):
        if len(target) + stop - start > MAX_FRAMING:
            raise too_large()
        target.extend(data[start:stop])

    with raw.open("xb") as output:

        def part(data, start, stop):
            nonlocal file_size
            size = stop - start
            if field == b"file":
                file_size += size
                if file_size > MAX_FILE:
                    raise too_large()
                output.write(data[start:stop])
            else:
                if len(metadata) + size > MAX_METADATA:
                    raise too_large()
                metadata.extend(data[start:stop])

        callbacks: MultipartCallbacks = {
            "on_part_begin": begin,
            "on_header_field": lambda data, start, stop: append_header(
                key, data, start, stop
            ),
            "on_header_value": lambda data, start, stop: append_header(
                value, data, start, stop
            ),
            "on_header_end": end_header,
            "on_headers_finished": end_headers,
            "on_part_data": part,
            "on_end": end,
        }
        total = 0
        stream = request.stream()
        try:
            parser = MultipartParser(boundary, callbacks)
            while True:
                try:
                    chunk = await asyncio.wait_for(anext(stream), INACTIVITY_SECONDS)
                except StopAsyncIteration:
                    break
                total += len(chunk)
                if total > MAX_FILE + MAX_METADATA + MAX_FRAMING:
                    raise too_large()
                await run_in_threadpool(parser.write, chunk)
                if total - file_size - len(metadata) > MAX_FRAMING:
                    raise too_large()
            parser.finalize()
        except TimeoutError as exc:
            raise LibraryError(422, "E_IMPORT_TIMEOUT", "The upload timed out") from exc
        except (MultipartParseError, ClientDisconnect) as exc:
            raise malformed() from exc
    if not completed or fields != {b"file", b"metadata"}:
        raise malformed()
    try:
        validated = json.loads(
            metadata.decode("utf-8"), parse_constant=reject_non_json_number
        )
    except (ValueError, RecursionError) as exc:
        raise LibraryError(400, "E_JSON", "Malformed metadata JSON") from exc
    extension = Path(filename).suffix.lower()
    with raw.open("rb") as input_file:
        magic = input_file.read(4)
    if extension not in {".csv", ".parquet"} or (extension == ".parquet") != (
        magic == b"PAR1"
    ):
        raise LibraryError(415, "E_FORMAT", "Unsupported or mismatched candle format")
    path = raw.rename(stage / ("candles" + extension))
    return path, filename, validated
