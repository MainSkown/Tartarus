import contextlib
import random
import struct

import pytest
from impacket import ntlm as impacket_ntlm
from impacket import spnego as impacket_spnego
from impacket.smbserver import outputToJohnFormat
from support import START, FakeClock

from lan_session import HostSpec
from lan_sim.ntlm import (
    MAX_NTLM_BYTES,
    NtlmAttempt,
    NtlmFormatError,
    challenge_message,
    exported_session_key,
    new_challenge,
    ntlm_message_type,
    parse_authenticate,
    spnego_accept,
    spnego_challenge,
    spnego_reject,
    unwrap_ntlmssp,
    verify,
)

CHALLENGE = bytes.fromhex("0123456789abcdef")
PASSWORD = "Passw0rd!"
HOST = HostSpec(
    "fs01.corp.local",
    "192.168.150.200",
    "Windows Server 2019",
    (("Administrator", PASSWORD), ("svc_backup", "Backup2020")),
    (),
)
HEADER_BYTES = 64


def client_authenticate(user, password, domain="CORP", *, use_ntlmv2=True, challenge=CHALLENGE):
    """What impacket's own client sends in answer to our challenge, and the key it exports."""
    type1 = impacket_ntlm.getNTLMSSPType1("WS01", domain)
    type1["flags"] |= impacket_ntlm.NTLMSSP_NEGOTIATE_KEY_EXCH
    type2 = challenge_message(HOST, challenge, FakeClock())
    type3, exported_key = impacket_ntlm.getNTLMSSPType3(
        type1, type2, user, password, domain, use_ntlmv2=use_ntlmv2
    )
    return type3.getData(), exported_key


def authenticate_blob(  # noqa: PLR0913
    *,
    lm=b"",
    nt=b"",
    domain="CORP",
    user="admin",
    workstation="WS01",
    session_key=b"",
    flags=impacket_ntlm.NTLMSSP_NEGOTIATE_UNICODE,
    encoding="utf-16le",
    header_override=None,
):
    """A hand-built AUTHENTICATE_MESSAGE, for the shapes impacket's client never produces."""
    payloads = [
        lm,
        nt,
        domain.encode(encoding),
        user.encode(encoding),
        workstation.encode(encoding),
        session_key,
    ]
    offset = HEADER_BYTES
    triples = []
    for payload in payloads:
        triples += [len(payload), len(payload), offset]
        offset += len(payload)
    header = struct.pack("<8sI" + "HHI" * 6 + "I", b"NTLMSSP\x00", 3, *triples, flags)
    if header_override:
        header = header_override(header)
    return header + b"".join(payloads)


class TestChallengeMessage:
    def message(self, host=HOST, challenge=CHALLENGE):
        return challenge_message(host, challenge, FakeClock())

    def test_it_is_a_challenge_message_carrying_the_challenge(self):
        blob = self.message()
        assert ntlm_message_type(blob) == 2
        assert impacket_ntlm.NTLMAuthChallenge(blob)["challenge"] == CHALLENGE

    def test_it_names_the_host_and_its_domain_in_every_form_a_client_may_check(self):
        blob = self.message()
        pairs = impacket_ntlm.AV_PAIRS(impacket_ntlm.NTLMAuthChallenge(blob)["TargetInfoFields"])
        names = {key: pairs[key][1].decode("utf-16le") for key in (1, 2, 3, 4, 5)}
        assert names == {
            impacket_ntlm.NTLMSSP_AV_HOSTNAME: "FS01",
            impacket_ntlm.NTLMSSP_AV_DOMAINNAME: "CORP",
            impacket_ntlm.NTLMSSP_AV_DNS_HOSTNAME: "fs01.corp.local",
            impacket_ntlm.NTLMSSP_AV_DNS_DOMAINNAME: "corp.local",
            impacket_ntlm.NTLMSSP_AV_DNS_TREENAME: "corp.local",
        }

    def test_the_target_name_is_the_netbios_name_of_the_host(self):
        challenge = impacket_ntlm.NTLMAuthChallenge(self.message())
        assert challenge["domain_name"].decode("utf-16le") == "FS01"

    def test_the_timestamp_comes_from_the_injected_clock(self):
        pairs = impacket_ntlm.AV_PAIRS(
            impacket_ntlm.NTLMAuthChallenge(self.message())["TargetInfoFields"]
        )
        (filetime,) = struct.unpack("<Q", pairs[impacket_ntlm.NTLMSSP_AV_TIME][1])
        unix_seconds = (filetime - 116444736000000000) / 10_000_000
        assert unix_seconds == START.timestamp()

    def test_the_timestamp_follows_the_clock(self):
        clock = FakeClock()
        clock.advance(90.5)
        blob = challenge_message(HOST, CHALLENGE, clock)
        pairs = impacket_ntlm.AV_PAIRS(impacket_ntlm.NTLMAuthChallenge(blob)["TargetInfoFields"])
        (filetime,) = struct.unpack("<Q", pairs[impacket_ntlm.NTLMSSP_AV_TIME][1])
        assert (filetime - 116444736000000000) / 10_000_000 == START.timestamp() + 90.5

    def test_the_version_is_windows_server_2019(self):
        blob = self.message()
        assert blob[48:56] == bytes.fromhex("0a0063450000000f")

    def test_it_advertises_signing_and_extended_session_security(self):
        flags = impacket_ntlm.NTLMAuthChallenge(self.message())["flags"]
        for required in (
            impacket_ntlm.NTLMSSP_NEGOTIATE_SIGN,
            impacket_ntlm.NTLMSSP_NEGOTIATE_ALWAYS_SIGN,
            impacket_ntlm.NTLMSSP_NEGOTIATE_EXTENDED_SESSIONSECURITY,
            impacket_ntlm.NTLMSSP_NEGOTIATE_KEY_EXCH,
            impacket_ntlm.NTLMSSP_NEGOTIATE_TARGET_INFO,
        ):
            assert flags & required

    @pytest.mark.parametrize("challenge", [b"", b"short", b"123456789"])
    def test_a_challenge_that_is_not_eight_bytes_is_refused(self, challenge):
        with pytest.raises(ValueError, match="8 bytes"):
            self.message(challenge=challenge)


class TestNewChallenge:
    def test_it_is_eight_bytes_from_the_random_source(self):
        asked = []

        def source(count):
            asked.append(count)
            return b"\x07" * count

        assert new_challenge(source) == b"\x07" * 8
        assert asked == [8]

    def test_the_default_source_is_random(self):
        assert len(new_challenge()) == 8
        assert new_challenge() != new_challenge()

    def test_a_source_that_returns_the_wrong_length_is_refused(self):
        with pytest.raises(ValueError, match="8 bytes"):
            new_challenge(lambda _: b"x")


class TestParseAuthenticate:
    def test_it_reads_the_names_a_real_client_sends(self):
        blob, _ = client_authenticate("Administrator", PASSWORD, "CORP")
        attempt = parse_authenticate(blob, CHALLENGE)
        assert (attempt.user, attempt.domain, attempt.workstation) == (
            "Administrator",
            "CORP",
            "WS01",
        )
        assert attempt.is_v2
        assert not attempt.anonymous

    def test_the_hashcat_line_is_what_impacket_writes_for_ntlmv2(self):
        blob, _ = client_authenticate("Administrator", PASSWORD, "CORP")
        parsed = impacket_ntlm.NTLMAuthChallengeResponse()
        parsed.fromString(blob)
        expected = outputToJohnFormat(
            CHALLENGE, parsed["user_name"], parsed["domain_name"], parsed["lanman"], parsed["ntlm"]
        )
        assert expected["hash_version"] == "ntlmv2"
        assert parse_authenticate(blob, CHALLENGE).hashcat == expected["hash_string"]

    def test_the_hashcat_line_is_what_impacket_writes_for_ntlmv1(self):
        blob, _ = client_authenticate("Administrator", PASSWORD, "CORP", use_ntlmv2=False)
        parsed = impacket_ntlm.NTLMAuthChallengeResponse()
        parsed.fromString(blob)
        expected = outputToJohnFormat(
            CHALLENGE, parsed["user_name"], parsed["domain_name"], parsed["lanman"], parsed["ntlm"]
        )
        assert expected["hash_version"] == "ntlm"
        attempt = parse_authenticate(blob, CHALLENGE)
        assert not attempt.is_v2
        assert attempt.hashcat == expected["hash_string"]

    def test_the_ntlmv2_line_has_the_five_fields_hashcat_5600_wants(self):
        blob, _ = client_authenticate("Administrator", PASSWORD, "CORP")
        user, empty, domain, challenge, proof_and_blob = parse_authenticate(
            blob, CHALLENGE
        ).hashcat.split(":", 4)
        proof, client_blob = proof_and_blob.split(":")
        assert (user, empty, domain, challenge) == ("Administrator", "", "CORP", CHALLENGE.hex())
        assert len(proof) == 32
        assert client_blob.startswith("0101000000000000")

    def test_an_anonymous_login_has_no_user_and_no_response(self):
        attempt = parse_authenticate(
            authenticate_blob(user="", lm=b"\x00", domain="", workstation=""), CHALLENGE
        )
        assert attempt.anonymous
        assert attempt.hashcat == ""

    def test_an_anonymous_login_may_carry_no_lm_response_at_all(self):
        assert parse_authenticate(authenticate_blob(user=""), CHALLENGE).anonymous

    def test_an_empty_user_with_a_response_is_not_anonymous(self):
        blob = authenticate_blob(user="", nt=b"\x01" * 24, lm=b"\x02" * 24)
        assert not parse_authenticate(blob, CHALLENGE).anonymous

    def test_an_lmv2_only_response_has_nothing_hashcat_can_crack(self):
        attempt = parse_authenticate(authenticate_blob(lm=b"\x02" * 24), CHALLENGE)
        assert not attempt.is_v2
        assert attempt.hashcat == ""

    def test_oem_names_are_read_when_unicode_was_not_negotiated(self):
        blob = authenticate_blob(flags=0, encoding="latin-1", user="admin", domain="CORP")
        attempt = parse_authenticate(blob, CHALLENGE)
        assert (attempt.user, attempt.domain) == ("admin", "CORP")

    def test_the_attempt_keeps_the_pieces_verify_needs(self):
        blob, _ = client_authenticate("Administrator", PASSWORD, "CORP")
        attempt = parse_authenticate(blob, CHALLENGE)
        assert attempt.challenge == CHALLENGE
        assert len(attempt.nt_response) > 48
        assert len(attempt.lm_response) == 24
        assert len(attempt.encrypted_session_key) == 16

    def test_bytes_after_the_message_are_ignored(self):
        blob, _ = client_authenticate("Administrator", PASSWORD, "CORP")
        assert parse_authenticate(blob + b"\x00" * 16, CHALLENGE).user == "Administrator"

    def test_a_challenge_of_the_wrong_length_is_a_programming_error(self):
        with pytest.raises(ValueError, match="8 bytes"):
            parse_authenticate(authenticate_blob(), b"short")


class TestMalformedAuthenticate:
    def test_every_truncation_of_a_real_message_parses_or_is_a_format_error(self):
        blob, _ = client_authenticate("Administrator", PASSWORD, "CORP")
        for length in range(len(blob)):
            with contextlib.suppress(NtlmFormatError):
                parse_authenticate(blob[:length], CHALLENGE)

    def test_a_message_cut_inside_its_header_or_payload_is_refused(self):
        blob, _ = client_authenticate("Administrator", PASSWORD, "CORP")
        for length in (0, 11, HEADER_BYTES - 1, len(blob) - 1):
            with pytest.raises(NtlmFormatError):
                parse_authenticate(blob[:length], CHALLENGE)

    def test_a_real_message_with_random_bytes_changed_never_raises_anything_else(self):
        generator = random.Random(1234)  # noqa: S311
        template, _ = client_authenticate("Administrator", PASSWORD, "CORP")
        for _ in range(2000):
            blob = bytearray(template)
            for _ in range(generator.randint(1, 6)):
                blob[generator.randrange(len(blob))] = generator.randrange(256)
            with contextlib.suppress(NtlmFormatError):
                parse_authenticate(bytes(blob), CHALLENGE)

    def test_random_garbage_behind_a_valid_signature_never_raises_anything_else(self):
        generator = random.Random(99)  # noqa: S311
        for _ in range(2000):
            garbage = generator.randbytes(generator.randint(0, 400))
            with contextlib.suppress(NtlmFormatError):
                parse_authenticate(b"NTLMSSP\x00\x03\x00\x00\x00" + garbage, CHALLENGE)

    @pytest.mark.parametrize("blob", [b"", b"NTLMSSP", b"NTLMSSP\x00", b"\x00" * 64, b"x" * 1000])
    def test_blobs_that_are_not_ntlm_are_refused(self, blob):
        with pytest.raises(NtlmFormatError):
            parse_authenticate(blob, CHALLENGE)

    def test_a_different_message_type_is_refused(self):
        blob = bytearray(authenticate_blob())
        blob[8] = 1
        with pytest.raises(NtlmFormatError, match="not an AUTHENTICATE"):
            parse_authenticate(bytes(blob), CHALLENGE)

    def test_a_ten_megabyte_blob_is_refused_before_it_is_read(self):
        with pytest.raises(NtlmFormatError, match="at most"):
            parse_authenticate(authenticate_blob() + b"\x00" * (10 * 1024 * 1024), CHALLENGE)

    def test_the_largest_accepted_message_is_the_cap(self):
        padded = authenticate_blob() + b"\x00" * (MAX_NTLM_BYTES - len(authenticate_blob()))
        assert parse_authenticate(padded, CHALLENGE).user == "admin"
        with pytest.raises(NtlmFormatError):
            parse_authenticate(padded + b"\x00", CHALLENGE)

    @pytest.mark.parametrize("field", range(6))
    def test_an_offset_past_the_end_of_the_message_is_refused(self, field):
        def point_outside(header):
            fields = list(struct.unpack("<8sI" + "HHI" * 6 + "I", header))
            fields[4 + 3 * field] = 0xFFFFFFF0
            return struct.pack("<8sI" + "HHI" * 6 + "I", *fields)

        blob = authenticate_blob(
            lm=b"\x01" * 24,
            nt=b"\x02" * 24,
            session_key=b"\x03" * 16,
            header_override=point_outside,
        )
        with pytest.raises(NtlmFormatError, match="outside"):
            parse_authenticate(blob, CHALLENGE)

    @pytest.mark.parametrize("field", range(6))
    def test_a_length_that_runs_past_the_end_is_refused(self, field):
        def grow(header):
            fields = list(struct.unpack("<8sI" + "HHI" * 6 + "I", header))
            fields[2 + 3 * field] = 0xFFFF
            return struct.pack("<8sI" + "HHI" * 6 + "I", *fields)

        blob = authenticate_blob(
            lm=b"\x01" * 24, nt=b"\x02" * 24, session_key=b"\x03" * 16, header_override=grow
        )
        with pytest.raises(NtlmFormatError):
            parse_authenticate(blob, CHALLENGE)

    def test_a_field_that_overlaps_the_header_is_refused(self):
        def into_header(header):
            fields = list(struct.unpack("<8sI" + "HHI" * 6 + "I", header))
            fields[4 + 3 * 3] = 0
            return struct.pack("<8sI" + "HHI" * 6 + "I", *fields)

        with pytest.raises(NtlmFormatError, match="outside"):
            parse_authenticate(authenticate_blob(header_override=into_header), CHALLENGE)

    def test_zero_lengths_with_any_offset_are_an_empty_message(self):
        def wild_offsets(header):
            fields = list(struct.unpack("<8sI" + "HHI" * 6 + "I", header))
            for field in range(6):
                fields[2 + 3 * field] = 0
                fields[3 + 3 * field] = 0
                fields[4 + 3 * field] = 0xFFFFFFFF
            return struct.pack("<8sI" + "HHI" * 6 + "I", *fields)

        blob = authenticate_blob(header_override=wild_offsets)
        attempt = parse_authenticate(blob, CHALLENGE)
        assert (attempt.user, attempt.domain, attempt.workstation) == ("", "", "")
        assert attempt.anonymous

    @pytest.mark.parametrize("length", [1, 2, 7, 25, 47])
    def test_an_nt_response_of_an_impossible_length_is_refused(self, length):
        with pytest.raises(NtlmFormatError, match="NT response"):
            parse_authenticate(authenticate_blob(nt=b"\x01" * length), CHALLENGE)

    @pytest.mark.parametrize("length", [2, 16, 23, 25, 100])
    def test_an_lm_response_of_an_impossible_length_is_refused(self, length):
        with pytest.raises(NtlmFormatError, match="LM response"):
            parse_authenticate(authenticate_blob(lm=b"\x01" * length), CHALLENGE)

    @pytest.mark.parametrize("length", [1, 8, 15, 17, 64])
    def test_an_encrypted_session_key_of_an_impossible_length_is_refused(self, length):
        with pytest.raises(NtlmFormatError, match="session key"):
            parse_authenticate(authenticate_blob(session_key=b"\x01" * length), CHALLENGE)

    def test_a_utf16_name_of_odd_length_is_refused(self):
        blob = authenticate_blob(user="admin") + b""
        broken = bytearray(blob)
        broken[36] -= 1
        with pytest.raises(NtlmFormatError, match="odd length"):
            parse_authenticate(bytes(broken), CHALLENGE)

    def test_a_name_with_a_lone_surrogate_is_refused(self):
        blob = authenticate_blob(user="ad")
        broken = blob.replace("ad".encode("utf-16le"), b"\x00\xd8\x61\x00")
        with pytest.raises(NtlmFormatError, match="UTF-16"):
            parse_authenticate(broken, CHALLENGE)

    @pytest.mark.parametrize("user", ["ad:min", "ad\nmin", "ad\x00min", "admin\x1b[0m", "x\x7f"])
    def test_a_name_that_would_break_the_hashcat_line_or_a_log_is_refused(self, user):
        with pytest.raises(NtlmFormatError, match="control character or a colon"):
            parse_authenticate(authenticate_blob(user=user), CHALLENGE)

    def test_a_name_over_the_cap_is_refused(self):
        with pytest.raises(NtlmFormatError, match="too long"):
            parse_authenticate(authenticate_blob(user="a" * 600), CHALLENGE)


class TestVerify:
    def test_the_right_password_verifies_and_yields_the_session_base_key(self):
        blob, _ = client_authenticate("Administrator", PASSWORD, "CORP")
        verdict = verify(parse_authenticate(blob, CHALLENGE), HOST)
        assert verdict.known_account
        assert verdict.verified
        assert verdict.session_base_key is not None
        assert len(verdict.session_base_key) == 16

    def test_the_exported_key_is_the_one_the_client_signs_with(self):
        blob, client_key = client_authenticate("Administrator", PASSWORD, "CORP")
        attempt = parse_authenticate(blob, CHALLENGE)
        verdict = verify(attempt, HOST)
        assert verdict.session_base_key is not None
        assert exported_session_key(attempt, verdict.session_base_key) == client_key

    def test_without_key_exchange_the_base_key_is_the_exported_key(self):
        attempt = parse_authenticate(authenticate_blob(flags=1), CHALLENGE)
        assert exported_session_key(attempt, b"\x09" * 16) == b"\x09" * 16

    def test_a_wrong_password_is_a_known_account_that_does_not_verify(self):
        blob, _ = client_authenticate("Administrator", "wrong", "CORP")
        verdict = verify(parse_authenticate(blob, CHALLENGE), HOST)
        assert verdict == verdict.__class__(
            known_account=True, verified=False, session_base_key=None
        )

    def test_a_login_against_another_challenge_does_not_verify(self):
        blob, _ = client_authenticate("Administrator", PASSWORD, "CORP")
        other = bytes.fromhex("fedcba9876543210")
        assert not verify(parse_authenticate(blob, other), HOST).verified

    def test_a_tampered_blob_does_not_verify(self):
        blob, _ = client_authenticate("Administrator", PASSWORD, "CORP")
        attempt = parse_authenticate(blob, CHALLENGE)
        nt = bytearray(attempt.nt_response)
        nt[20] ^= 1
        tampered = NtlmAttempt(**{**attempt.__dict__, "nt_response": bytes(nt)})
        assert not verify(tampered, HOST).verified

    def test_an_unknown_user_is_not_a_known_account(self):
        blob, _ = client_authenticate("nobody", PASSWORD, "CORP")
        verdict = verify(parse_authenticate(blob, CHALLENGE), HOST)
        assert (verdict.known_account, verdict.verified, verdict.session_base_key) == (
            False,
            False,
            None,
        )

    @pytest.mark.parametrize("user", ["ADMINISTRATOR", "administrator"])
    def test_the_user_matches_in_any_case(self, user):
        blob, _ = client_authenticate(user, PASSWORD, "CORP")
        assert verify(parse_authenticate(blob, CHALLENGE), HOST).verified

    def test_the_domain_the_client_sent_is_part_of_the_proof(self):
        blob, _ = client_authenticate("Administrator", PASSWORD, "WORKGROUP")
        assert verify(parse_authenticate(blob, CHALLENGE), HOST).verified

    def test_a_user_sent_as_domain_backslash_user_verifies(self):
        blob, _ = client_authenticate("CORP\\Administrator", PASSWORD, "")
        attempt = parse_authenticate(blob, CHALLENGE)
        assert verify(attempt, HOST).verified

    def test_ntlmv1_is_known_but_never_verified(self):
        blob, _ = client_authenticate("Administrator", PASSWORD, "CORP", use_ntlmv2=False)
        verdict = verify(parse_authenticate(blob, CHALLENGE), HOST)
        assert (verdict.known_account, verdict.verified, verdict.session_base_key) == (
            True,
            False,
            None,
        )

    def test_an_lmv2_only_response_is_known_but_never_verified(self):
        attempt = parse_authenticate(
            authenticate_blob(user="Administrator", lm=b"\x02" * 24), CHALLENGE
        )
        assert verify(attempt, HOST) == verify(attempt, HOST).__class__(True, False, None)

    def test_an_anonymous_login_knows_no_account(self):
        attempt = parse_authenticate(authenticate_blob(user=""), CHALLENGE)
        assert not verify(attempt, HOST).known_account

    def test_an_account_with_an_empty_password_verifies_against_the_empty_password(self):
        host = HostSpec("fs01.corp.local", "192.168.150.200", "", (("guest", ""),), ())
        blob, _ = client_authenticate("guest", "", "CORP")
        assert verify(parse_authenticate(blob, CHALLENGE), host).verified

    def test_a_password_that_cannot_be_encoded_never_verifies(self):
        host = HostSpec("fs01.corp.local", "192.168.150.200", "", (("admin", "\ud800"),), ())
        attempt = parse_authenticate(authenticate_blob(nt=b"\x01" * 60), CHALLENGE)
        assert verify(attempt, host).known_account
        assert not verify(attempt, host).verified

    def test_the_ms_nlmp_documented_ntlmv2_vector(self):
        # [MS-NLMP] 4.2.4: User / Domain / Password, ServerChallenge 0123456789abcdef,
        # ClientChallenge aa*8, zero time, AV pairs NbDomain "Domain" and NbComputer "Server",
        # followed by four bytes of padding. The proof and the base key are the documented ones.
        host = HostSpec("server.domain.local", "192.168.150.200", "", (("User", "Password"),), ())
        av_pairs = (
            b"\x02\x00\x0c\x00"
            + "Domain".encode("utf-16le")
            + b"\x01\x00\x0c\x00"
            + "Server".encode("utf-16le")
            + b"\x00\x00\x00\x00"
        )
        client_blob = b"\x01\x01" + b"\x00" * 6 + b"\x00" * 8 + b"\xaa" * 8 + b"\x00" * 4
        client_blob += av_pairs + b"\x00" * 4
        proof = bytes.fromhex("68cd0ab851e51c96aabc927bebef6a1c")
        blob = authenticate_blob(
            user="User", domain="Domain", nt=proof + client_blob, lm=b"\x00" * 24
        )
        attempt = parse_authenticate(blob, CHALLENGE)
        verdict = verify(attempt, host)
        assert verdict.verified
        assert verdict.session_base_key == bytes.fromhex("8de40ccadbc14a82f15cb0ad0de95ca3")


class TestMessageType:
    @pytest.mark.parametrize(
        ("blob", "expected"),
        [
            (b"NTLMSSP\x00\x01\x00\x00\x00", 1),
            (b"NTLMSSP\x00\x02\x00\x00\x00abc", 2),
            (b"NTLMSSP\x00\x03\x00\x00\x00", 3),
        ],
    )
    def test_the_type_is_read_from_the_header(self, blob, expected):
        assert ntlm_message_type(blob) == expected

    @pytest.mark.parametrize(
        "blob",
        [
            b"",
            b"NTLMSSP\x00",
            b"NTLMSSP\x00\x01",
            b"NTLMSSX\x00\x01\x00\x00\x00",
            b"NTLMSSP\x00\x04\x00\x00\x00",
            b"NTLMSSP\x00\x00\x00\x00\x00",
        ],
    )
    def test_anything_else_is_a_format_error(self, blob):
        with pytest.raises(NtlmFormatError):
            ntlm_message_type(blob)

    def test_it_reads_a_real_negotiate_message(self):
        assert ntlm_message_type(impacket_ntlm.getNTLMSSPType1("WS01", "CORP").getData()) == 1


class TestSpnego:
    def test_the_challenge_wrapper_is_an_accept_incomplete_token_naming_ntlmssp(self):
        blob = challenge_message(HOST, CHALLENGE, FakeClock())
        token = impacket_spnego.SPNEGO_NegTokenResp(spnego_challenge(blob))
        assert token["NegState"] == b"\x01"
        assert (
            token["SupportedMech"]
            == impacket_spnego.TypesMech["NTLMSSP - Microsoft NTLM Security Support Provider"]
        )
        assert token["ResponseToken"] == blob

    def test_the_reject_token_says_reject(self):
        assert impacket_spnego.SPNEGO_NegTokenResp(spnego_reject())["NegState"] == b"\x02"

    def test_the_accept_token_says_accept_completed(self):
        assert impacket_spnego.SPNEGO_NegTokenResp(spnego_accept())["NegState"] == b"\x00"

    def test_a_wrapped_message_is_found_inside_its_token(self):
        blob = challenge_message(HOST, CHALLENGE, FakeClock())
        assert unwrap_ntlmssp(spnego_challenge(blob)) == blob

    def test_a_raw_message_is_returned_as_it_is(self):
        blob = impacket_ntlm.getNTLMSSPType1("WS01", "CORP").getData()
        assert unwrap_ntlmssp(blob) == blob

    def test_a_negotiate_token_init_from_a_client_is_unwrapped(self):
        init = impacket_spnego.SPNEGO_NegTokenInit()
        init["MechTypes"] = [
            impacket_spnego.TypesMech["NTLMSSP - Microsoft NTLM Security Support Provider"]
        ]
        type1 = impacket_ntlm.getNTLMSSPType1("WS01", "CORP").getData()
        init["MechToken"] = type1
        assert unwrap_ntlmssp(init.getData()) == type1

    @pytest.mark.parametrize("data", [b"", b"\x60\x00", b"NTLMSS", b"x" * 500])
    def test_data_without_a_message_is_none(self, data):
        assert unwrap_ntlmssp(data) is None

    def test_oversize_data_is_none_even_with_a_message_in_it(self):
        assert unwrap_ntlmssp(b"NTLMSSP\x00" + b"\x00" * (10 * 1024 * 1024)) is None
