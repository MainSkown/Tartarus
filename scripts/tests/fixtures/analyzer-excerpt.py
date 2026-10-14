# Excerpt of analyzer/windows/analyzer.py at the CAPE_REF pinned in docker-compose.yml: the two
# places cape/patches/skip-packaged-apps.py anchors on, copied verbatim, with just enough stubs
# around them to run PipeHandler._handle_process. The build itself checks the same anchors against
# the real file; this fixture lets the patch be tested without the image.
import logging
import os
import timeit
from typing import Union

log = logging.getLogger("analyzer")

INJECT_LIST = []
PROTECTED_PATH_LIST = []
INTERACTIVE_MODE = False
ANALYSIS_TIMED_OUT = False


def _normalized_protected_path(path: Union[str, bytes]) -> bytes:
    if isinstance(path, str):
        path = path.encode()
    return path.lower()


def in_protected_path(path: Union[str, bytes]) -> bool:
    """Checks if a path is protected."""
    return _normalized_protected_path(path) in PROTECTED_PATH_LIST


def add_protected_path(name: Union[str, bytes]):
    """Adds a pathname to the protected list"""
    PROTECTED_PATH_LIST.append(_normalized_protected_path(name))


def add_pid_to_aux_modules(pid):
    pass


class FakeProcess:
    injected = []

    def __init__(self, options=None, config=None, pid=0, thread_id=0):
        self.pid = pid

    def get_filepath(self):
        return FakeProcess.filepaths[self.pid]

    def is_64bit(self):
        return True

    def inject(self, interest):
        FakeProcess.injected.append(self.pid)

    def close(self):
        pass


Process = FakeProcess


class PipeHandler:
    def _handle_process(self, data):
        """Request for injection into a process."""
        # Parse the process identifier.
        # PROCESS:1:1824,2856
        # We parse the process ID.
        pid_s, tid_s = data.split(b",", 1)
        process_id = int(pid_s)
        thread_id  = int(tid_s)
        if process_id and not ANALYSIS_TIMED_OUT:
            if process_id not in (self.analyzer.pid, self.analyzer.ppid):
                # We inject the process only if it's not being
                # monitored already, otherwise we would generate
                # polluted logs.
                if process_id not in self.analyzer.process_list.pids:
                    if process_id not in INJECT_LIST:
                        INJECT_LIST.append(process_id)
                    # Open the process and inject the DLL.
                    proc = Process(
                        options=self.analyzer.options,
                        config=self.analyzer.config,
                        pid=process_id,
                        thread_id=thread_id,
                    )
                    filepath = proc.get_filepath()  # .encode('utf8', 'replace')
                    # if it's a URL analysis, provide the URL to all processes as
                    # the "interest" -- this will allow capemon to see in the
                    # child browser process that a URL analysis is occurring
                    if self.analyzer.config.category == "file" or self.analyzer.NUM_INJECTED > 1:
                        interest = filepath
                    else:
                        interest = self.analyzer.config.target
                    if filepath.lower() in self.analyzer.files.files:
                        self.analyzer.files.delete_file(filepath, process_id)
                    is_64bit = proc.is_64bit()
                    filename = os.path.basename(filepath)
                    if self.analyzer.SERVICES_PID and process_id == self.analyzer.SERVICES_PID:
                        self.analyzer.CRITICAL_PROCESS_LIST.append(int(self.analyzer.SERVICES_PID))
                    log.info("Announced %s process name: %s pid: %d", "64-bit" if is_64bit else "32-bit", filename, process_id)
                    # We want to prevent multiple injection attempts if one is already underway
                    if not in_protected_path(filename):
                        _ = proc.inject(interest)
                        self.analyzer.LASTINJECT_TIME = timeit.default_timer()
                        self.analyzer.NUM_INJECTED += 1
                    proc.close()
            else:
                log.warning("Received request to inject process with pid %d, skipped", process_id)
        # return self._inject_process(int(data), None, 0)
