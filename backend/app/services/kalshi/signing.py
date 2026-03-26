"""
RSA-PSS request signing for the Kalshi REST API.

Signing rules (from https://docs.kalshi.com/getting_started/api_keys):
  message  = timestamp_ms + HTTP_METHOD + path_without_query
  algorithm = RSA-PSS / SHA-256 / salt_length=DIGEST_LENGTH
  encoding  = base64 standard
  path      = full URL path from root, e.g. /trade-api/v2/portfolio/balance
"""

import base64
import datetime

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey


def current_timestamp_ms() -> str:
    """Return the current UTC time as a millisecond-epoch string."""
    return str(int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000))


def sign_request(
    private_key: RSAPrivateKey,
    timestamp_ms: str,
    method: str,
    path: str,
) -> str:
    """
    Produce a base64-encoded RSA-PSS signature for a Kalshi REST request.

    Args:
        private_key:  Loaded RSA private key.
        timestamp_ms: Millisecond epoch string (value of KALSHI-ACCESS-TIMESTAMP).
        method:       HTTP method in uppercase, e.g. "GET".
        path:         Full URL path without query string, e.g. "/trade-api/v2/portfolio/balance".
    """
    path_no_query = path.split("?")[0]
    message = f"{timestamp_ms}{method}{path_no_query}".encode("utf-8")
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")
