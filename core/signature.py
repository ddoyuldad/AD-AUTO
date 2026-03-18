import hmac
import hashlib
import time


def get_timestamp() -> str:
    return str(int(time.time() * 1000))


def generate_signature(timestamp: str, method: str, uri: str, secret_key: str) -> str:
    message = f"{timestamp}.{method}.{uri}"
    signature = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    import base64
    return base64.b64encode(signature).decode("utf-8")
