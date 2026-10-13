/*
 * Benign behaviour sample for the M0b self-test, built with mingw-w64. It performs the four
 * observable actions check 10 looks for, then exits: spawn a child process, write a file, set a
 * registry value and resolve a domain name. It is deliberately harmless -- no persistence, no
 * network payload, no file beyond its own temp file -- so capemon has distinct events to log
 * without anything that INetSim or the analyst must treat as real malware.
 */
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <stdio.h>

static void spawn_child(void) {
    STARTUPINFOA si = { .cb = sizeof si };
    PROCESS_INFORMATION pi = { 0 };
    char cmd[] = "cmd.exe /c ver";
    if (CreateProcessA(NULL, cmd, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi)) {
        WaitForSingleObject(pi.hProcess, 5000);
        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
    }
}

static void write_marker_file(void) {
    char path[MAX_PATH];
    GetTempPathA(sizeof path, path);
    strncat(path, "tartarus-benign.txt", sizeof path - strlen(path) - 1);
    HANDLE h = CreateFileA(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h != INVALID_HANDLE_VALUE) {
        const char text[] = "tartarus benign sample was here\r\n";
        DWORD written = 0;
        WriteFile(h, text, (DWORD)(sizeof text - 1), &written, NULL);
        CloseHandle(h);
    }
}

static void set_registry_value(void) {
    HKEY key;
    if (RegCreateKeyExA(HKEY_CURRENT_USER, "Software\\Tartarus", 0, NULL, 0,
                        KEY_SET_VALUE, NULL, &key, NULL) == ERROR_SUCCESS) {
        const char value[] = "benign";
        RegSetValueExA(key, "SelfTest", 0, REG_SZ, (const BYTE *)value, (DWORD)sizeof value);
        RegCloseKey(key);
    }
}

static void resolve_name(void) {
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) return;
    struct addrinfo hints = { .ai_family = AF_INET, .ai_socktype = SOCK_STREAM };
    struct addrinfo *result = NULL;
    if (getaddrinfo("tartarus-selftest.example", "80", &hints, &result) == 0) {
        freeaddrinfo(result);
    }
    WSACleanup();
}

int main(void) {
    spawn_child();
    write_marker_file();
    set_registry_value();
    resolve_name();
    printf("tartarus benign sample done\n");
    return 0;
}
