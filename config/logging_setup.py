import atexit
import logging
import os
import queue
import re
import socket
import sys
import threading
from datetime import datetime


DEFAULT_LOG_TABLE = "CUSTOMER_SUPPORT_BOT_LOGS.CHAT_DATA.DBD_APP_LOG"
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def _qualified_table_name():
    configured = os.getenv("APP_LOG_TABLE", DEFAULT_LOG_TABLE)
    parts = configured.split(".")
    if len(parts) != 3 or not all(_IDENTIFIER_PATTERN.fullmatch(part) for part in parts):
        raise ValueError("APP_LOG_TABLE must be a database.schema.table identifier")
    return ".".join(parts)


class _SnowflakeLogWriter:
    def __init__(self, table_name):
        self._table_name = table_name
        self._queue = queue.Queue()
        self._stop = object()
        self._thread = threading.Thread(
            target=self._run,
            name="snowflake-app-log-writer",
            daemon=True,
        )
        self._thread.start()

    def submit(self, created_at, stream_name, message):
        self._queue.put((created_at, stream_name, message))

    def close(self):
        if self._thread.is_alive():
            self._queue.put(self._stop)
            self._thread.join(timeout=10)

    def _run(self):
        pending = []
        while True:
            try:
                item = self._queue.get(timeout=1)
            except queue.Empty:
                item = None

            stopping = item is self._stop
            if item is not None and not stopping:
                pending.append(item)

            if pending and (stopping or item is None or len(pending) >= 100):
                try:
                    self._write_batch(pending)
                    pending.clear()
                except Exception as exc:
                    # Never feed writer failures back into the Snowflake log queue.
                    sys.__stderr__.write(f"Snowflake application logging failed: {exc}\n")
                    sys.__stderr__.flush()
                    pending.clear()

            if stopping:
                return

    def _write_batch(self, rows):
        from services.snowflake_service import SnowflakeService

        database, schema, _ = self._table_name.split(".")
        conn = SnowflakeService().connect(database=database, schema=schema)
        cursor = conn.cursor()
        try:
            cursor.executemany(
                f"INSERT INTO {self._table_name} (LOGGED_AT, STREAM, MESSAGE, HOST_NAME) "
                "VALUES (%s, %s, %s, %s)",
                [(*row, socket.gethostname()) for row in rows],
            )
            conn.commit()
        finally:
            cursor.close()
            conn.close()


class _SnowflakeLogStream:
    def __init__(self, original_stream, writer, stream_name):
        self._original_stream = original_stream
        self._writer = writer
        self._stream_name = stream_name
        self._lock = threading.RLock()
        self._pending = ""
        self._gcs_snowflake_log_stream = True

    def write(self, message):
        with self._lock:
            self._original_stream.write(message)
            self._original_stream.flush()
            self._pending += message
            while "\n" in self._pending:
                line, self._pending = self._pending.split("\n", 1)
                self._submit(line)

    def flush(self):
        with self._lock:
            self._original_stream.flush()
            if self._pending:
                self._submit(self._pending)
                self._pending = ""

    def _submit(self, line):
        if line.strip():
            self._writer.submit(datetime.now().astimezone(), self._stream_name, line)

    def isatty(self):
        return self._original_stream.isatty()

    def fileno(self):
        return self._original_stream.fileno()

    @property
    def encoding(self):
        return getattr(self._original_stream, "encoding", "utf-8")


_writer = None
_setup_lock = threading.Lock()


def setup_snowflake_logging():
    global _writer
    with _setup_lock:
        table_name = _qualified_table_name()
        if _writer is None:
            _writer = _SnowflakeLogWriter(table_name)
            atexit.register(_writer.close)

        if not getattr(sys.stdout, "_gcs_snowflake_log_stream", False):
            sys.stdout = _SnowflakeLogStream(sys.stdout, _writer, "stdout")
        if not getattr(sys.stderr, "_gcs_snowflake_log_stream", False):
            sys.stderr = _SnowflakeLogStream(sys.stderr, _writer, "stderr")

        logger = logging.getLogger()
        if not any(getattr(handler, "_gcs_console_log_handler", False) for handler in logger.handlers):
            handler = logging.StreamHandler(sys.stderr)
            handler._gcs_console_log_handler = True
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)

        return table_name


# Compatibility for callers that have not yet migrated to the new function name.
def setup_daily_logging(log_dir=None):
    return setup_snowflake_logging()
