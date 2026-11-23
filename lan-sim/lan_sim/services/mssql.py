"""MSSQL (TDS 7.x) as a SQL Server 2019 host: a login honeypot that answers a few queries.

A SQL login with any password is accepted, because the client derives nothing from the password and
a tool that goes on to run queries is the evidence we want. Integrated security runs the NTLM
exchange through `lan_sim.ntlm`, logs the NetNTLMv2 material and always refuses the login. SQL text
is read, logged capped and answered from canned data; it is never interpreted or executed.
"""

import secrets
from collections.abc import Callable

from lan_sim import ntlm
from lan_sim.identity import netbios_name
from lan_sim.service import Connection
from lan_sim.services import mssql_sql, mssql_tokens, mssql_wire
from lan_sim.services.mssql_wire import Login7Request, TdsFormatError, TdsVersion

SQL_BATCH_REQUEST = "sql batch"
SQL_RPC_REQUEST = "sql rpc"
MALFORMED_TDS = "malformed tds"
MAX_LOGGED_STATEMENT_CHARACTERS = 500


class MssqlService:
    kind = "mssql"

    def __init__(self, random_source: Callable[[int], bytes] = secrets.token_bytes) -> None:
        self._random_source = random_source

    async def serve(self, connection: Connection) -> None:
        """Speaks TDS on `connection`; a malformed message is logged and ends the connection."""
        conversation = _Conversation(connection, self._random_source)
        try:
            await conversation.run()
        except (TdsFormatError, ntlm.NtlmFormatError) as error:
            connection.log.service_request(name=MALFORMED_TDS, detail=str(error))


SERVICE = MssqlService()


class _Conversation:
    def __init__(self, connection: Connection, random_source: Callable[[int], bytes]) -> None:
        self._connection = connection
        self._random_source = random_source
        self._server = netbios_name(connection.host)
        self._login_user = ""

    async def run(self) -> None:
        message = await mssql_wire.read_message(self._connection)
        if message.type == mssql_wire.PRELOGIN:
            mssql_wire.check_prelogin(message.payload)
            await self._reply(mssql_wire.prelogin_response())
            message = await mssql_wire.read_message(self._connection)
        if message.type != mssql_wire.LOGIN7:
            raise TdsFormatError("a message other than Login7 where it was due")
        login = mssql_wire.parse_login7(message.payload)
        if await self._logged_in(login):
            await self._serve_requests(login.version)

    async def _logged_in(self, login: Login7Request) -> bool:
        if login.integrated_security:
            await self._refuse_integrated_login(login)
            return False
        return await self._sql_login(login)

    async def _sql_login(self, login: Login7Request) -> bool:
        accepted = bool(login.user)
        self._connection.log.login_attempt(
            user=login.user,
            domain="",
            mechanism="sql",
            secret=login.password,
            success=accepted,
        )
        if accepted:
            self._login_user = login.user
            await self._reply(mssql_tokens.login_success(login.version, self._server))
        else:
            await self._reply(mssql_tokens.login_failure(login.version, self._server, ""))
        return accepted

    async def _refuse_integrated_login(self, login: Login7Request) -> None:
        negotiate = ntlm.unwrap_ntlmssp(login.sspi)
        if negotiate is None:
            self._log_ntlm_attempt(user="", domain="", secret="", success=False)
            await self._reply(mssql_tokens.login_failure(login.version, self._server, ""))
            return
        if ntlm.ntlm_message_type(negotiate) != ntlm.NEGOTIATE_MESSAGE:
            raise TdsFormatError("an SSPI message other than NEGOTIATE in Login7")
        challenge = ntlm.new_challenge(self._random_source)
        token = ntlm.challenge_message(self._connection.host, challenge, self._connection.clock)
        wrapped = not login.sspi.startswith(ntlm.NTLMSSP_SIGNATURE)
        await self._reply(
            mssql_tokens.sspi_token(ntlm.spnego_challenge(token) if wrapped else token)
        )
        message = await mssql_wire.read_message(self._connection)
        if message.type != mssql_wire.SSPI_MESSAGE:
            raise TdsFormatError("a message other than the SSPI authenticate where it was due")
        authenticate = ntlm.unwrap_ntlmssp(message.payload)
        if authenticate is None:
            raise TdsFormatError("an SSPI message without NTLM")
        attempt = ntlm.parse_authenticate(authenticate, challenge)
        verdict = ntlm.verify(attempt, self._connection.host)
        self._log_ntlm_attempt(
            user=attempt.user,
            domain=attempt.domain,
            secret=attempt.hashcat,
            success=verdict.verified,
        )
        shown = f"{attempt.domain}\\{attempt.user}" if attempt.domain else attempt.user
        await self._reply(mssql_tokens.login_failure(login.version, self._server, shown))

    def _log_ntlm_attempt(self, *, user: str, domain: str, secret: str, success: bool) -> None:
        self._connection.log.login_attempt(
            user=user, domain=domain, mechanism="ntlm", secret=secret, success=success
        )

    async def _serve_requests(self, version: TdsVersion) -> None:
        while True:
            message = await mssql_wire.read_message(self._connection)
            if message.type == mssql_wire.SQL_BATCH:
                await self._answer_batch(version, message.payload)
            elif message.type == mssql_wire.RPC_REQUEST:
                self._log_rpc(message.payload)
                await self._reply(mssql_tokens.done(version))
            elif message.type == mssql_wire.ATTENTION:
                await self._reply(mssql_tokens.done(version, attention=True))
            else:
                raise TdsFormatError("a message type that does not belong in a session")

    async def _answer_batch(self, version: TdsVersion, payload: bytes) -> None:
        text = mssql_sql.batch_text(payload)
        self._connection.log.service_request(
            name=SQL_BATCH_REQUEST, detail=text[:MAX_LOGGED_STATEMENT_CHARACTERS]
        )
        answer = mssql_sql.answer_for(text, self._connection.host, self._login_user)
        if answer is None:
            await self._reply(mssql_tokens.done(version))
        else:
            await self._reply(mssql_tokens.scalar_result(version, answer.column, answer.value))

    def _log_rpc(self, payload: bytes) -> None:
        self._connection.log.service_request(
            name=SQL_RPC_REQUEST, detail=mssql_sql.rpc_procedure(payload) or ""
        )

    async def _reply(self, tokens: bytes) -> None:
        await self._connection.write(mssql_wire.frame_message(mssql_wire.TABULAR_RESPONSE, tokens))
