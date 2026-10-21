/* P-spike sample: harmless. DNS, one HTTP GET and one HTTPS handshake against whatever the route answers,
   then starts ping.exe and runs a 2-byte stub (xor eax,eax; ret) from a PAGE_EXECUTE_READWRITE region
   holding an MZ-looking buffer in it with CreateRemoteThread. */
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <stdio.h>
#include <string.h>

static SOCKET connect_to(const char *host, const char *port) {
    struct addrinfo hints = { .ai_family = AF_INET, .ai_socktype = SOCK_STREAM }, *res = NULL;
    if (getaddrinfo(host, port, &hints, &res) != 0) return INVALID_SOCKET;
    SOCKET s = socket(res->ai_family, res->ai_socktype, res->ai_protocol);
    if (s != INVALID_SOCKET && connect(s, res->ai_addr, (int)res->ai_addrlen) != 0) { closesocket(s); s = INVALID_SOCKET; }
    freeaddrinfo(res);
    return s;
}

static void http_get(const char *host, const char *path) {
    SOCKET s = connect_to(host, "80");
    if (s == INVALID_SOCKET) return;
    char req[512], buf[1024];
    snprintf(req, sizeof req, "GET %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: p9-spike/1.0\r\nConnection: close\r\n\r\n", path, host);
    send(s, req, (int)strlen(req), 0);
    while (recv(s, buf, sizeof buf, 0) > 0) {}
    closesocket(s);
}

static void tls_hello(const char *host) {
    SOCKET s = connect_to(host, "443");
    if (s == INVALID_SOCKET) return;
    /* a minimal TLS 1.2 ClientHello with SNI */
    unsigned char hello[512]; int n = 0; size_t hl = strlen(host);
    unsigned char body[400]; int b = 0;
    body[b++]=3; body[b++]=3; for (int i=0;i<32;i++) body[b++]=(unsigned char)(i*7+1);
    body[b++]=0; body[b++]=0; body[b++]=2; body[b++]=0x00; body[b++]=0x2f;
    body[b++]=1; body[b++]=0;
    int ext = 0; unsigned char e[200];
    e[ext++]=0; e[ext++]=0; int sl=(int)hl+5; e[ext++]=(unsigned char)(sl>>8); e[ext++]=(unsigned char)sl;
    int ll=(int)hl+3; e[ext++]=(unsigned char)(ll>>8); e[ext++]=(unsigned char)ll; e[ext++]=0;
    e[ext++]=(unsigned char)(hl>>8); e[ext++]=(unsigned char)hl; memcpy(e+ext, host, hl); ext+=(int)hl;
    body[b++]=(unsigned char)(ext>>8); body[b++]=(unsigned char)ext; memcpy(body+b,e,ext); b+=ext;
    unsigned char hs[420]; int h=0; hs[h++]=1; hs[h++]=0; hs[h++]=(unsigned char)(b>>8); hs[h++]=(unsigned char)b; memcpy(hs+h,body,b); h+=b;
    hello[n++]=0x16; hello[n++]=3; hello[n++]=1; hello[n++]=(unsigned char)(h>>8); hello[n++]=(unsigned char)h; memcpy(hello+n,hs,h); n+=h;
    send(s, (char*)hello, n, 0);
    char buf[1024]; recv(s, buf, sizeof buf, 0);
    closesocket(s);
}

static void inject(void) {
    STARTUPINFOA si = { .cb = sizeof si }; PROCESS_INFORMATION pi = { 0 };
    char cmd[] = "C:\\Windows\\System32\\PING.EXE -n 1000 127.0.0.1";
    if (!CreateProcessA(NULL, cmd, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi)) return;
    Sleep(2000);
    unsigned char code[0x400] = { 'M', 'Z' };
    code[0x200] = 0x31; code[0x201] = 0xC0; code[0x202] = 0xC3;
    void *remote = VirtualAllocEx(pi.hProcess, NULL, 0x2000, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!remote) return;
    WriteProcessMemory(pi.hProcess, remote, code, sizeof code, NULL);
    HANDLE t = CreateRemoteThread(pi.hProcess, NULL, 0, (LPTHREAD_START_ROUTINE)((char*)remote + 0x200), NULL, 0, NULL);
    if (t) { WaitForSingleObject(t, 3000); CloseHandle(t); }
}

int main(void) {
    WSADATA wsa; WSAStartup(MAKEWORD(2, 2), &wsa);
    http_get("p9-spike-one.example", "/index.html?a=1");
    http_get("p9-spike-two.example", "/payload.bin");
    tls_hello("p9-spike-secure.example");
    inject();
    Sleep(5000);
    return 0;
}
