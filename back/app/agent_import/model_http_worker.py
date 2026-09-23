"""Stdlib-only timed HTTP worker; no dotenv/DB access and no secret/body logging."""
import http.client
import json
import sys
import time
from urllib.parse import urlsplit


def main() -> None:
    request = json.loads(sys.stdin.buffer.read(8 * 1024 * 1024 + 1))
    data = json.dumps(request["body"], ensure_ascii=False, allow_nan=False).encode("utf-8") if request["body"] is not None else None
    target = urlsplit(request["url"])
    if target.scheme not in {"http", "https"} or not target.hostname or target.username or target.password:
        raise ValueError("Invalid model endpoint")
    started = time.monotonic()
    timings = {"phase": "worker_ready", "connection_seconds": None, "first_content_seconds": None}
    request_id = None

    def progress(phase):
        timings["phase"] = phase
        sys.stderr.write(json.dumps(timings) + "\n")
        sys.stderr.flush()

    connection_type = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
    connection = connection_type(target.hostname, target.port, timeout=request["timeout"])
    try:
        # DNS/TCP/TLS combined connection time, NOT time spent by the model.
        progress("connecting")
        connection.connect()
        timings["connection_seconds"] = time.monotonic() - started
        progress("sending_request")
        path = target.path or "/"
        if target.query:
            path += "?" + target.query
        connection.request(request["method"], path, body=data, headers={
            "Authorization": "Bearer " + request["api_key"], "Content-Type": "application/json", "Accept": "application/json",
        })
        timings["request_sent_seconds"] = time.monotonic() - started
        progress("waiting_response_headers")
        response = connection.getresponse()
        timings["response_headers_seconds"] = time.monotonic() - started
        request_id = response.getheader("x-request-id")
        progress("reading_body")
        if not 200 <= response.status < 300:
            # Never forward credentials to an unapproved redirect destination.
            result = {"http_status": response.status}
        else:
            first = response.read(1)
            timings["first_body_byte_seconds"] = time.monotonic() - started if first else None
            progress("reading_body")
            raw = first + response.read(16 * 1024 * 1024)
            timings["complete_receive_seconds"] = time.monotonic() - started
            if len(raw) > 16 * 1024 * 1024:
                raise ValueError("response budget exceeded")
            progress("parsing_json")
            parsed_at = time.monotonic()
            parsed = json.loads(raw)
            result = {"response": {"value": parsed} if request.get("wrap_response") is True else parsed}
            timings["json_parse_seconds"] = time.monotonic() - parsed_at
            progress("complete")
            result["response"]["_viewer_transport"] = {"timings": timings, "response_bytes": len(raw), "request_id": request_id}
    except Exception as exc:
        result = {"error": type(exc).__name__}
    finally:
        connection.close()
    result["transport_timings"] = timings
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
