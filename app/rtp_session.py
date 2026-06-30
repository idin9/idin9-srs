import asyncio
import struct
import logging
from typing import Optional

logger = logging.getLogger(__name__)

RTP_HEADER_SIZE = 12


def parse_rtp_header(data: bytes) -> Optional[dict]:
    if len(data) < RTP_HEADER_SIZE:
        return None

    first_byte = data[0]
    version = (first_byte >> 6) & 0x03
    padding = (first_byte >> 5) & 0x01
    extension = (first_byte >> 4) & 0x01
    csrc_count = first_byte & 0x0F

    second_byte = data[1]
    marker = (second_byte >> 7) & 0x01
    payload_type = second_byte & 0x7F

    sequence_number = struct.unpack("!H", data[2:4])[0]
    timestamp = struct.unpack("!I", data[4:8])[0]
    ssrc = struct.unpack("!I", data[8:12])[0]

    header_size = RTP_HEADER_SIZE + (csrc_count * 4)
    if extension:
        if len(data) >= header_size + 4:
            ext_length = struct.unpack("!H", data[header_size + 2 : header_size + 4])[0]
            header_size += 4 + (ext_length * 4)

    payload = data[header_size:]

    return {
        "version": version,
        "padding": padding,
        "extension": extension,
        "csrc_count": csrc_count,
        "marker": marker,
        "payload_type": payload_type,
        "sequence_number": sequence_number,
        "timestamp": timestamp,
        "ssrc": ssrc,
        "payload": payload,
    }


class RtpSession:
    def __init__(
        self,
        session_id: str,
        local_port: int,
        remote_ip: str,
        remote_port: int,
        on_audio_callback,
        loop: asyncio.AbstractEventLoop,
        host: str = "0.0.0.0",
    ):
        self.session_id = session_id
        self.local_port = local_port
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.on_audio = on_audio_callback
        self.loop = loop
        self.host = host
        self.transport: Optional[asyncio.DatagramTransport] = None
        self._running = False
        self._payload_type: Optional[int] = None

    async def start(self):
        try:
            self.transport, _ = await self.loop.create_datagram_endpoint(
                lambda: RtpProtocol(self),
                local_addr=(self.host, self.local_port),
            )
            self._running = True
            logger.info(
                "RTP session %s listening on port %s (remote %s:%s)",
                self.session_id,
                self.local_port,
                self.remote_ip,
                self.remote_port,
            )
        except Exception as e:
            logger.error("Failed to start RTP session %s: %s", self.session_id, e)

    def handle_rtp_packet(self, data: bytes):
        if not self._running:
            return

        try:
            header = parse_rtp_header(data)
            if header is None:
                return

            if self._payload_type is None:
                self._payload_type = header["payload_type"]
                logger.info(
                    "Session %s detected payload type %s",
                    self.session_id,
                    self._payload_type,
                )

            payload = header["payload"]
            if payload:
                self.on_audio(self.session_id, payload, header["payload_type"])
        except Exception as e:
            logger.warning("RTP packet error on %s: %s", self.session_id, e)

    def stop(self):
        self._running = False
        if self.transport:
            self.transport.close()
            self.transport = None
        logger.info("RTP session %s stopped", self.session_id)


class RtpProtocol(asyncio.DatagramProtocol):
    def __init__(self, session: RtpSession):
        self.session = session

    def datagram_received(self, data: bytes, addr: tuple):
        self.session.handle_rtp_packet(data)

    def connection_lost(self, exc: Optional[Exception]) -> None:
        if exc is not None:
            logger.warning("RTP transport lost for session %s: %s", self.session.session_id, exc)
