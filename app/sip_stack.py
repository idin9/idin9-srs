import asyncio
import re
import socket
import uuid
import logging
from datetime import datetime
from typing import Optional, Callable

from .mime_parser import (
    parse_multipart_body,
    extract_sdp_media_streams,
    extract_recording_metadata,

    build_sdp_with_streams,
)

logger = logging.getLogger(__name__)

SIP_VERSION = "SIP/2.0"

RESPONSE_TEMPLATE = (
    "{sip_version} {status_code} {reason_phrase}\r\n"
    "{via}"
    "{contact}"
    "{to}"
    "{from_header}"
    "Call-ID: {call_id}\r\n"
    "CSeq: {cseq}\r\n"
    "Content-Type: application/sdp\r\n"
    "Content-Length: {content_length}\r\n"
    "\r\n"
    "{body}"
)


def parse_sip_message(data: bytes) -> dict:
    text = data.decode("utf-8", errors="replace")
    lines = text.split("\r\n")
    if not lines:
        return {}

    request_line = lines[0]
    parts = request_line.split(" ")
    method = parts[0] if len(parts) > 0 else ""
    uri = parts[1] if len(parts) > 1 else ""

    headers: dict[str, str] = {}
    body_start = text.find("\r\n\r\n")
    header_section = text[:body_start] if body_start != -1 else text

    for line in header_section.split("\r\n")[1:]:
        if ":" in line:
            key, val = line.split(":", 1)
            headers[key.strip()] = val.strip()

    body = ""
    if body_start != -1:
        body = text[body_start + 4:]

    return {
        "method": method,
        "uri": uri,
        "headers": headers,
        "body": body,
        "raw": data,
    }


def build_response(
    status_code: int,
    reason: str,
    request_msg: dict,
    contact_uri: str,
    rtp_ports: list[int],
    server_ip: str,
) -> bytes:
    headers = request_msg["headers"]
    call_id = headers.get("Call-ID", "unknown")
    cseq_line = headers.get("CSeq", "1 INVITE")
    from_h = headers.get("From", "<sip:unknown>")
    to_h = headers.get("To", "<sip:unknown>")
    via = headers.get("Via", "SIP/2.0/UDP unknown")

    contact = f"Contact: <sip:{contact_uri}>\r\n"
    via_line = f"Via: {via}\r\n"
    to_line = f"To: {to_h}\r\n"
    from_line = f"From: {from_h}\r\n"

    sdp = build_sdp_with_streams(server_ip, rtp_ports)

    response = RESPONSE_TEMPLATE.format(
        sip_version=SIP_VERSION,
        status_code=status_code,
        reason_phrase=reason,
        via=via_line,
        contact=contact,
        to=to_line,
        from_header=from_line,
        call_id=call_id,
        cseq=cseq_line,
        content_length=len(sdp.encode("utf-8")),
        body=sdp,
    )
    return response.encode("utf-8")


def build_ack(message: dict) -> bytes:
    headers = message["headers"]
    via = headers.get("Via", "SIP/2.0/UDP unknown")
    from_h = headers.get("From", "<sip:unknown>")
    to_h = headers.get("To", "<sip:unknown>")
    call_id = headers.get("Call-ID", "unknown")
    cseq = headers.get("CSeq", "1 INVITE")
    route = headers.get("Route", "")

    text = f"ACK {message['uri']} SIP/2.0\r\n"
    text += f"Via: {via}\r\n"
    if route:
        text += f"Route: {route}\r\n"
    text += f"From: {from_h}\r\n"
    text += f"To: {to_h}\r\n"
    text += f"Call-ID: {call_id}\r\n"
    text += f"CSeq: {cseq}\r\n"
    text += "Max-Forwards: 70\r\n"
    text += "Content-Length: 0\r\n\r\n"
    return text.encode("utf-8")


class Idin9SrsServer:
    def __init__(
        self,
        host: str,
        port: int,
        rtp_port_allocator,
        on_new_session_callback,
        loop: asyncio.AbstractEventLoop,
        on_end_session_callback=None,
    ):
        self.host = host
        self.port = port
        self.rtp_port_allocator = rtp_port_allocator
        self.on_new_session = on_new_session_callback
        self.on_end_session = on_end_session_callback
        self.loop = loop
        self.transport: Optional[asyncio.DatagramTransport] = None
        self.server_ip = self._resolve_server_ip(host)

    @staticmethod
    def _resolve_server_ip(host: str) -> str:
        if host and host != "0.0.0.0" and host != "::":
            return host
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0)
            s.connect(("10.254.254.254", 1))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    async def start(self):
        self.transport, _ = await self.loop.create_datagram_endpoint(
            lambda: Idin9SrsProtocol(self),
            local_addr=(self.host, self.port),
        )
        logger.info("SIPREC server listening on udp %s:%s", self.host, self.port)

    def stop(self):
        if self.transport:
            self.transport.close()

    def handle_request(self, data: bytes, addr: tuple):
        msg = parse_sip_message(data)
        method = msg.get("method", "")
        if method == "INVITE":
            asyncio.run_coroutine_threadsafe(
                self._handle_invite(msg, addr), self.loop
            )
        elif method == "BYE":
            asyncio.run_coroutine_threadsafe(
                self._handle_bye(msg, addr), self.loop
            )
        elif method == "ACK":
            logger.info("Received ACK from %s for %s", addr, msg.get("headers", {}).get("Call-ID", "unknown"))

    async def _handle_invite(self, msg: dict, addr: tuple):
        call_id = msg["headers"].get("Call-ID", str(uuid.uuid4()))
        content_type = msg["headers"].get("Content-Type", "")

        sdp_body = msg.get("body", "")
        xml_metadata = {}
        remote_ip = addr[0]

        # Check for multipart MIME (SDP + XML metadata)
        if "multipart/mixed" in content_type or "multipart" in content_type:
            parts = parse_multipart_body(content_type, msg["body"])
            for part in parts:
                ct = part['headers'].get('content-type', '')
                if 'application/sdp' in ct:
                    sdp_body = part['content']
                elif 'application/xml' in ct or 'text/xml' in ct or 'xml' in ct:
                    xml_metadata = extract_recording_metadata(part['content'])
        elif 'application/sdp' in content_type:
            sdp_body = msg.get("body", "")

        # Parse SDP to get media streams
        streams = extract_sdp_media_streams(sdp_body)
        if not streams:
            logger.warning("No valid SDP media streams in INVITE from %s", addr)
            return

        # Use connection IP from SDP if available
        if streams[0].get('remote_ip'):
            remote_ip = streams[0]['remote_ip']

        # Extract caller/callee from XML metadata first, fall back to SIP headers
        caller = xml_metadata.get('caller', msg["headers"].get("From", ""))
        callee = xml_metadata.get('callee', msg["headers"].get("To", ""))

        # Allocate RTP ports for each stream
        allocated_ports = []
        for stream in streams:
            rtp_port = self.rtp_port_allocator()
            if not rtp_port:
                logger.error("No available RTP ports for stream in session %s", call_id)
                return
            allocated_ports.append(rtp_port)
            stream['allocated_port'] = rtp_port

        # Ensure remote_port is set from parsed SDP
        for i, stream in enumerate(streams):
            stream['remote_ip'] = remote_ip

        # Send 200 OK with SDP containing all allocated ports
        response_200 = build_response(
            200, "OK", msg,
            f"idin9-srs@{self.server_ip}:{self.port}",
            allocated_ports,
            self.server_ip,
        )
        self.transport.sendto(response_200, addr)
        logger.info(
            "Sent 200 OK for call %s, %d stream(s) on ports %s",
            call_id, len(allocated_ports), allocated_ports,
        )

        # Send ACK
        try:
            response_ack = build_ack(msg)
            self.transport.sendto(response_ack, addr)
        except Exception:
            pass

        # Notify session manager
        await self.on_new_session(
            session_id=call_id,
            streams=streams,
            caller=caller,
            callee=callee,
            xml_metadata=xml_metadata,
        )

    async def _handle_bye(self, msg: dict, addr: tuple):
        call_id = msg["headers"].get("Call-ID", "")
        try:
            response = build_response(
                200, "OK", msg,
                f"idin9-srs@{self.server_ip}:{self.port}",
                [0],
                self.server_ip,
            )
            self.transport.sendto(response, addr)
        except Exception as e:
            logger.error("Failed to send 200 OK for BYE: %s", e)
        logger.info("Session %s ended via BYE", call_id)
        if self.on_end_session:
            try:
                await self.on_end_session(call_id)
            except Exception as e:
                logger.error("Failed to stop session %s via BYE: %s", call_id, e)


class Idin9SrsProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: Idin9SrsServer):
        self.server = server

    def datagram_received(self, data: bytes, addr: tuple):
        self.server.handle_request(data, addr)

    def connection_lost(self, exc: Optional[Exception]) -> None:
        logger.warning("SIP transport lost: %s", exc)
