"""
Multipart MIME parser for SIPREC.
Handles multipart/mixed bodies containing SDP and XML metadata.
"""

import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Any


def parse_multipart_body(content_type: str, body: str) -> List[Dict[str, str]]:
    """
    Parse a multipart MIME body into individual parts with their headers.

    Returns a list of dicts with keys 'headers' (dict) and 'content' (str).
    """
    match = re.search(r'boundary="?([^";\r\n]+)"?', content_type)
    if not match:
        return []

    boundary = match.group(1)
    parts = []

    delimiter = f"--{boundary}"
    raw_parts = body.split(delimiter)

    for part in raw_parts:
        part = part.strip('\r\n').strip('\n')
        if not part or part == '--':
            continue

        header_lines = []
        content_start = 0

        lines = part.split('\n')
        for i, line in enumerate(lines):
            stripped = line.rstrip('\r')
            if stripped == '':
                content_start = i + 1
                break
            header_lines.append(stripped)
        else:
            content_start = len(lines)

        headers = {}
        for h in header_lines:
            if ':' in h:
                key, val = h.split(':', 1)
                headers[key.strip().lower()] = val.strip()

        content = '\n'.join(lines[content_start:]).strip('\r\n').strip('\n')

        parts.append({
            'headers': headers,
            'content': content,
        })

    return parts


def extract_sdp_media_streams(sdp_body: str) -> List[Dict[str, Any]]:
    """
    Parse SDP body and extract all m=audio lines with their codec info.

    Returns list of stream dicts with keys:
      - remote_port: int (RTP port)
      - codecs: dict mapping payload_type -> (codec_name, sample_rate)
    """
    streams = []
    conn_ip = None

    conn_match = re.search(r'c=IN IP4 (\S+)', sdp_body)
    if conn_match:
        conn_ip = conn_match.group(1)

    # Find all media lines and their attributes
    media_blocks = re.split(r'\r?\nm=', sdp_body)

    for block in media_blocks:
        if not block.strip():
            continue

        # If the block doesn't start with "audio", it might be the first part without m= prefix
        if not block.startswith('audio'):
            if block.strip() and not re.match(r'^(audio|video|text|application|message|image)', block):
                continue

        if block.startswith('audio'):
            block = block[6:]  # Remove "audio "

        lines = block.split('\r?\n') if '\n' not in block else block.split('\n')
        first_line = lines[0].strip() if lines else ''

        port_match = re.match(r'(\d+)', first_line)
        if not port_match:
            continue

        remote_port = int(port_match.group(1))
        codecs = {}
        payload_types = []

        for line in lines[1:]:
            line = line.strip()
            rtpmap_match = re.match(r'a=rtpmap:(\d+)\s+(\S+)/(\d+)', line)
            if rtpmap_match:
                pt = int(rtpmap_match.group(1))
                codec_name = rtpmap_match.group(2)
                sample_rate = int(rtpmap_match.group(3))
                codecs[pt] = (codec_name, sample_rate)
                payload_types.append(pt)

        streams.append({
            'remote_port': remote_port,
            'codecs': codecs,
            'payload_types': payload_types,
        })

    # Apply connection IP to all streams
    for stream in streams:
        stream['remote_ip'] = conn_ip

    return streams


def extract_siprec_metadata(xml_body: str) -> Dict[str, str]:
    """
    Parse SIPREC XML metadata and extract caller/callee info.
    Returns dict with possible keys: caller, callee, session_id, direction, etc.
    """
    metadata = {}

    try:
        root = ET.fromstring(xml_body)

        # Define namespaces
        ns = {
            'rec': 'urn:ietf:params:xml:ns:recording:1',
            '': 'urn:ietf:params:xml:ns:recording:1',
        }

        # Get session ID
        session_elem = root.find('.//rec:session/rec:sessionId', ns)
        if session_elem is not None:
            metadata['session_id'] = session_elem.text

        # Get all participants
        participants = root.findall('.//rec:participant', ns)
        participant_aors = []
        participant_names = []

        for p in participants:
            aor = p.find('rec:aor', ns)
            name = p.find('rec:nameID', ns)
            if aor is not None:
                participant_aors.append(aor.text)
            if name is not None:
                participant_names.append(name.text)

        # AudioCodes typically puts first participant as caller, second as callee
        if len(participant_aors) >= 2:
            metadata['caller'] = participant_aors[0]
            metadata['callee'] = participant_aors[1]
        elif len(participant_aors) == 1:
            metadata['caller'] = participant_aors[0]

        # Check for direction
        direction = root.find('.//rec:sessionRelation', ns)
        if direction is not None:
            metadata['direction'] = direction.get('type', '')

        # Check for session group ID
        group_id = root.find('.//rec:sessionGroupId', ns)
        if group_id is not None:
            metadata['group_id'] = group_id.text

    except ET.ParseError as e:
        pass
    except Exception as e:
        pass

    return metadata


def build_sdp_with_streams(server_ip: str, rtp_ports: List[int]) -> str:
    """
    Build an SDP response with multiple m=audio lines for dual-stream recording.

    rtp_ports: list of allocated RTP ports, one per stream.
    """
    session_id = str(int(datetime.utcnow().timestamp()))
    lines = [
        "v=0",
        f"o=- {session_id} 0 IN IP4 {server_ip}",
        "s=-",
        f"c=IN IP4 {server_ip}",
        "t=0 0",
    ]

    for port in rtp_ports:
        lines.extend([
            f"m=audio {port} RTP/AVP 0 8 18 111",
            "a=rtpmap:0 PCMU/8000",
            "a=rtpmap:8 PCMA/8000",
            "a=rtpmap:18 G729/8000",
            "a=rtpmap:111 opus/48000/2",
            "a=sendrecv",
            "a=rtcp-mux",
            "a=label:stream-{port}",
        ])

    return "\r\n".join(lines) + "\r\n"


from datetime import datetime
