"""The self-signed certificate each fake host presents to RDP clients, kept in memory only."""

import asyncio
import os
import ssl
import threading
from datetime import datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

MAX_CACHED_HOSTS = 64
KEY_BITS = 2048
BACKDATED = timedelta(days=1)
VALIDITY = timedelta(days=365)


class HostCertificates:
    """One certificate and TLS context per FQDN, made on the first connection to that host."""

    def __init__(self, cache_size: int = MAX_CACHED_HOSTS) -> None:
        self._cache_size = cache_size
        self._contexts: dict[str, ssl.SSLContext] = {}
        self._building = threading.Lock()

    async def context_for(self, fqdn: str, now: datetime) -> ssl.SSLContext:
        cached = self._contexts.get(fqdn)
        if cached is not None:
            return cached
        # Key generation takes a noticeable fraction of a second; keep it off the event loop.
        return await asyncio.to_thread(self._build_once, fqdn, now)

    def cached_hosts(self) -> list[str]:
        return list(self._contexts)

    def _build_once(self, fqdn: str, now: datetime) -> ssl.SSLContext:
        with self._building:
            context = self._contexts.get(fqdn)
            if context is None:
                context = _self_signed_context(fqdn, now)
                while len(self._contexts) >= self._cache_size:
                    del self._contexts[next(iter(self._contexts))]
                self._contexts[fqdn] = context
            return context


def _self_signed_context(fqdn: str, now: datetime) -> ssl.SSLContext:
    key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_BITS)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, fqdn)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - BACKDATED)
        .not_valid_after(now + VALIDITY)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(fqdn)]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    pem = certificate.public_bytes(serialization.Encoding.PEM) + key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return _context_from_pem(pem)


def _context_from_pem(pem: bytes) -> ssl.SSLContext:
    """`load_cert_chain` only takes a path: an anonymous memory file keeps the key off the disk."""
    descriptor = os.memfd_create("rdp-certificate")
    try:
        os.write(descriptor, pem)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(f"/proc/self/fd/{descriptor}")
        return context
    finally:
        os.close(descriptor)
