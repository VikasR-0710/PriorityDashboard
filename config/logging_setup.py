import logging
import os
import sys
from datetime import datetime
from threading import RLock


DEFAULT_LOG_DIR = "logs"


class _DailyLogStream:
    def __init__(self, original_stream, log_dir, stream_name):
        self._original_stream = original_stream
        self._log_dir = log_dir
        self._stream_name = stream_name
        self._lock = RLock()
        self._current_date = None
        self._file = None
        self._pending = ""
        self._gcs_daily_log_stream = True

    def _open_for_today(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self._current_date == today and self._file and not self._file.closed:
            return

        if self._file and not self._file.closed:
            self._file.close()

        os.makedirs(self._log_dir, exist_ok=True)
        path = os.path.join(self._log_dir, f"{today}.log")
        self._file = open(path, "a", encoding="utf-8")
        self._current_date = today

    def write(self, message):
        with self._lock:
            self._original_stream.write(message)
            self._original_stream.flush()
            self._open_for_today()
            self._pending += message
            while "\n" in self._pending:
                line, self._pending = self._pending.split("\n", 1)
                self._write_log_line(f"{line}\n")
            self._file.flush()

    def flush(self):
        with self._lock:
            self._original_stream.flush()
            if self._pending:
                self._open_for_today()
                self._write_log_line(self._pending)
                self._pending = ""
            if self._file and not self._file.closed:
                self._file.flush()

    def _write_log_line(self, line):
        if line.strip():
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._file.write(f"{timestamp} [{self._stream_name}] {line}")
        else:
            self._file.write(line)

    def isatty(self):
        return self._original_stream.isatty()

    def fileno(self):
        return self._original_stream.fileno()

    @property
    def encoding(self):
        return getattr(self._original_stream, "encoding", "utf-8")


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def setup_daily_logging(log_dir=None):
    root = _project_root()
    resolved_log_dir = log_dir or os.getenv("APP_LOG_DIR") or os.path.join(root, DEFAULT_LOG_DIR)
    os.makedirs(resolved_log_dir, exist_ok=True)

    if not getattr(sys.stdout, "_gcs_daily_log_stream", False):
        sys.stdout = _DailyLogStream(sys.stdout, resolved_log_dir, "stdout")
    if not getattr(sys.stderr, "_gcs_daily_log_stream", False):
        sys.stderr = _DailyLogStream(sys.stderr, resolved_log_dir, "stderr")

    logger = logging.getLogger()
    if not any(getattr(handler, "_gcs_console_log_handler", False) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler._gcs_console_log_handler = True
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    return resolved_log_dir
