import asyncio
import ssl
from datetime import timedelta

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from support import START

from lan_sim.services.rdp_tls import MAX_CACHED_HOSTS, HostCertificates


async def presented_certificate(context: ssl.SSLContext) -> x509.Certificate:
    async def handshake_only(reader, writer):
        writer.close()

    server = await asyncio.start_server(handshake_only, "127.0.0.1", 0, ssl=context)
    port = server.sockets[0].getsockname()[1]
    client_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client_context.check_hostname = False
    client_context.verify_mode = ssl.CERT_NONE
    _, writer = await asyncio.open_connection("127.0.0.1", port, ssl=client_context)
    der = writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
    writer.close()
    server.close()
    return x509.load_der_x509_certificate(der)


def test_the_certificate_is_self_signed_for_the_hosts_fqdn():
    async def scenario():
        context = await HostCertificates().context_for("fs01.corp.local", START)
        return await presented_certificate(context)

    certificate = asyncio.run(scenario())

    [common_name] = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    assert common_name.value == "fs01.corp.local"
    assert certificate.issuer == certificate.subject
    key = certificate.public_key()
    assert isinstance(key, rsa.RSAPublicKey)
    assert key.key_size >= 2048
    san = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    assert san.value.get_values_for_type(x509.DNSName) == ["fs01.corp.local"]
    assert certificate.not_valid_before_utc < START < certificate.not_valid_after_utc
    assert certificate.not_valid_after_utc - START < timedelta(days=800)


def test_a_host_gets_one_certificate_however_many_connections_ask():
    async def scenario():
        certificates = HostCertificates()
        contexts = await asyncio.gather(
            *(certificates.context_for("fs01.corp.local", START) for _ in range(8))
        )
        return contexts, certificates

    contexts, certificates = asyncio.run(scenario())

    assert all(context is contexts[0] for context in contexts)
    assert asyncio.run(certificates.context_for("fs01.corp.local", START)) is contexts[0]


def test_two_hosts_get_different_certificates():
    async def scenario():
        certificates = HostCertificates()
        first = await certificates.context_for("fs01.corp.local", START)
        second = await certificates.context_for("dc01.corp.local", START)
        return await presented_certificate(first), await presented_certificate(second)

    first, second = asyncio.run(scenario())

    assert first.public_key().public_numbers() != second.public_key().public_numbers()


def test_the_cache_does_not_grow_past_its_cap():
    certificates = HostCertificates(cache_size=2)

    async def scenario():
        for name in ("a.corp.local", "b.corp.local", "c.corp.local"):
            await certificates.context_for(name, START)

    asyncio.run(scenario())

    assert certificates.cached_hosts() == ["b.corp.local", "c.corp.local"]
    assert MAX_CACHED_HOSTS >= 16
