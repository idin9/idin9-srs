import os
import wave
import logging
import numpy as np
from typing import Optional
from collections import defaultdict

logger = logging.getLogger(__name__)

PAYLOAD_TYPE_PCMU = 0
PAYLOAD_TYPE_PCMA = 8
PAYLOAD_TYPE_G729 = 18
PAYLOAD_TYPE_OPUS = 111

# μ-law lookup table
MU_LAW_TABLE = [0] * 256

# A-law lookup table
A_LAW_TABLE = [0] * 256


def _build_mulaw_table():
    for i in range(256):
        val = ~i & 0xFF
        sign = (val & 0x80) >> 7
        exponent = (val >> 4) & 0x07
        mantissa = val & 0x0F
        sample = ((mantissa << 1) + 33) << exponent
        sample -= 33
        if sign:
            sample = -sample
        MU_LAW_TABLE[i] = sample


def _build_alaw_table():
    for i in range(256):
        val = i ^ 0x55
        sign = (val & 0x80) >> 7
        exponent = (val >> 4) & 0x07
        mantissa = val & 0x0F
        sample = ((mantissa << 4) + 0x08) << exponent
        if exponent > 0:
            sample += 0x0100
        if sign:
            sample = -sample
        A_LAW_TABLE[i] = sample


_build_mulaw_table()
_build_alaw_table()


def decode_pcmu(data: bytes) -> np.ndarray:
    samples = np.frombuffer(data, dtype=np.uint8)
    return np.array([MU_LAW_TABLE[s] for s in samples], dtype=np.int16)


def decode_pcma(data: bytes) -> np.ndarray:
    samples = np.frombuffer(data, dtype=np.uint8)
    return np.array([A_LAW_TABLE[s] for s in samples], dtype=np.int16)


def decode_g729(data: bytes) -> np.ndarray:
    """
    Decode G.729 encoded audio.
    G.729 uses 10ms frames = 10 bytes per frame at 8kHz = 80 samples.
    Without an external G.729 library, we output silence.
    Install 'libg729' or use a transcoding SBC configuration to use PCMU/PCMA instead.
    """
    try:
        import g729
        samples_per_frame = 80
        offset = 0
        result = np.array([], dtype=np.int16)
        while offset + 10 <= len(data):
            frame_data = data[offset:offset + 10]
            pcm = g729.decode(frame_data)
            result = np.append(result, np.frombuffer(pcm, dtype=np.int16))
            offset += 10
        return result
    except ImportError:
        logger.warning("G.729 not available (install 'g729' package). Outputting silence for %d bytes.", len(data))
        # Estimate: 10 bytes = 80 samples at 8kHz
        estimated_frames = len(data) // 10
        return np.zeros(estimated_frames * 80, dtype=np.int16)


def decode_opus(data: bytes) -> np.ndarray:
    try:
        import opuslib
        decoder = opuslib.Decoder(48000, 1)
        pcm = decoder.decode(data, 960)
        return np.frombuffer(pcm, dtype=np.int16)
    except ImportError:
        logger.warning("opuslib not available, returning empty PCM for opus packet")
        return np.array([], dtype=np.int16)


PAYLOAD_DECODERS = {
    PAYLOAD_TYPE_PCMU: decode_pcmu,
    PAYLOAD_TYPE_PCMA: decode_pcma,
    PAYLOAD_TYPE_G729: decode_g729,
    PAYLOAD_TYPE_OPUS: decode_opus,
}

SAMPLE_RATE = 8000


class AudioProcessor:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        # _buffers[session_id][stream_index] = list of sample arrays
        self._buffers: dict[str, dict[int, list[np.ndarray]]] = {}
        self._sample_counts: dict[str, dict[int, int]] = {}
        os.makedirs(output_dir, exist_ok=True)

    def feed_audio(self, session_id: str, stream_index: int, payload: bytes, payload_type: int):
        decoder = PAYLOAD_DECODERS.get(payload_type, PAYLOAD_DECODERS.get(PAYLOAD_TYPE_PCMU))
        try:
            samples = decoder(payload)
        except Exception as e:
            logger.error("Audio decode error session=%s type=%s: %s", session_id, payload_type, e)
            return
        if len(samples) == 0:
            return

        if session_id not in self._buffers:
            self._buffers[session_id] = {}
            self._sample_counts[session_id] = {}
        if stream_index not in self._buffers[session_id]:
            self._buffers[session_id][stream_index] = []
            self._sample_counts[session_id][stream_index] = 0

        self._buffers[session_id][stream_index].append(samples)
        self._sample_counts[session_id][stream_index] += len(samples)

    def get_audio_duration(self, session_id: str) -> float:
        stream_counts = self._sample_counts.get(session_id, {})
        if not stream_counts:
            return 0.0
        max_count = max(stream_counts.values())
        return max_count / SAMPLE_RATE

    def save_wav(self, session_id: str) -> Optional[str]:
        if session_id not in self._buffers or not self._buffers[session_id]:
            logger.warning("No audio data for session %s", session_id)
            return None

        streams = self._buffers[session_id]
        num_streams = len(streams)

        # Get samples for each stream, concatenated
        stream_samples = {}
        for idx in sorted(streams.keys()):
            if streams[idx]:
                stream_samples[idx] = np.concatenate(streams[idx])
            else:
                stream_samples[idx] = np.array([], dtype=np.int16)

        if not stream_samples:
            return None

        max_len = max(len(s) for s in stream_samples.values())
        # Pad shorter streams to match longest stream's length
        for idx in stream_samples:
            if len(stream_samples[idx]) < max_len:
                stream_samples[idx] = np.pad(
                    stream_samples[idx],
                    (0, max_len - len(stream_samples[idx])),
                    mode='constant',
                )

        filepath = os.path.join(self.output_dir, f"{session_id}.wav")

        if num_streams >= 2:
            # Stereo WAV: left = stream 0 (caller), right = stream 1 (callee)
            stereo = np.column_stack((
                stream_samples.get(0, np.zeros(max_len, dtype=np.int16)),
                stream_samples.get(1, np.zeros(max_len, dtype=np.int16)),
            )).flatten()
            with wave.open(filepath, "wb") as wf:
                wf.setnchannels(2)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(stereo.tobytes())
            logger.info(
                "Saved stereo WAV for session %s (%d channels, %s samples each)",
                session_id, num_streams, max_len,
            )
        else:
            # Mono WAV (single stream)
            samples = list(stream_samples.values())[0]
            with wave.open(filepath, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(samples.tobytes())
            logger.info(
                "Saved mono WAV for session %s (%s samples)",
                session_id, len(samples),
            )

        return filepath

    def split_stereo_wav(self, session_id: str, wav_path: str) -> Optional[list[str]]:
        if not os.path.exists(wav_path):
            return None
        try:
            with wave.open(wav_path, "rb") as wf:
                if wf.getnchannels() < 2:
                    return None
                frames = wf.readframes(wf.getnframes())
                sampwidth = wf.getsampwidth()
                framerate = wf.getframerate()
            samples = np.frombuffer(frames, dtype=np.int16).reshape(-1, 2)
            paths = []
            for ch in range(2):
                ch_path = os.path.join(self.output_dir, f"{session_id}.ch{ch}.wav")
                with wave.open(ch_path, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(sampwidth)
                    wf.setframerate(framerate)
                    wf.writeframes(samples[:, ch].tobytes())
                paths.append(ch_path)
            logger.info("Split stereo WAV into channels for session %s", session_id)
            return paths
        except Exception as e:
            logger.error("Failed to split stereo WAV for session %s: %s", session_id, e)
            return None

    def get_wav_path(self, session_id: str) -> Optional[str]:
        filepath = os.path.join(self.output_dir, f"{session_id}.wav")
        if os.path.exists(filepath):
            return filepath
        return None

    def process_final_audio(self, session_id: str, wav_path: str) -> str:
        """
        Convert WAV to OPUS if format is set to 'opus' and encrypt if enabled.
        Returns the final saved file path.
        """
        from .config import settings
        
        target_path = wav_path
        
        # 1. Convert to OPUS if requested
        if settings.audio_format == "opus":
            opus_path = convert_wav_to_opus(wav_path)
            if opus_path and os.path.exists(opus_path):
                target_path = opus_path
                # Delete the original WAV file
                try:
                    os.remove(wav_path)
                except OSError as e:
                    logger.warning("Failed to remove temporary WAV file %s: %s", wav_path, e)
            else:
                logger.warning("Conversion to OPUS failed, falling back to WAV")
                
        # 2. Encrypt if enabled
        if settings.encryption_enabled:
            password = settings.encryption_password or "idin9-srs-default-pass"
            enc_path = target_path + ".enc"
            try:
                encrypt_file(target_path, enc_path, password)
                # Delete the unencrypted target file
                try:
                    os.remove(target_path)
                except OSError as e:
                    logger.warning("Failed to remove unencrypted file %s: %s", target_path, e)
                target_path = enc_path
                logger.info("Successfully encrypted audio for session %s -> %s", session_id, enc_path)
            except Exception as e:
                logger.error("Encryption failed for session %s: %s", session_id, e)
                
        return target_path

    def clear(self, session_id: str):
        self._buffers.pop(session_id, None)
        self._sample_counts.pop(session_id, None)


def convert_wav_to_opus(wav_path: str) -> Optional[str]:
    import subprocess
    opus_path = wav_path.replace(".wav", ".opus")
    cmd = [
        "ffmpeg", "-y",
        "-i", wav_path,
        "-c:a", "libopus",
        "-b:a", "64k",
        opus_path
    ]
    try:
        logger.info("Converting %s to OPUS...", wav_path)
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return opus_path
    except subprocess.CalledProcessError as e:
        logger.error("Failed to convert WAV to OPUS: %s", e.stderr.decode(errors="replace"))
        return None
    except FileNotFoundError:
        logger.error("ffmpeg command not found on the system. Please install ffmpeg.")
        return None


def encrypt_file(in_path: str, out_path: str, password: str):
    import base64
    import os
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.fernet import Fernet
    
    with open(in_path, "rb") as f:
        data = f.read()
        
    salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    fernet = Fernet(key)
    encrypted_data = fernet.encrypt(data)
    
    with open(out_path, "wb") as f:
        f.write(salt + encrypted_data)


def decrypt_file(in_path: str, password: str) -> bytes:
    import base64
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.fernet import Fernet
    
    with open(in_path, "rb") as f:
        data = f.read()
        
    salt = data[:16]
    encrypted_data = data[16:]
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    fernet = Fernet(key)
    return fernet.decrypt(encrypted_data)
