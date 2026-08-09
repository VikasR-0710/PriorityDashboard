"""Asynchronous Snowflake application logging used by the original dashboard."""

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
_INTERNAL_LOG_MARKERS = (
    " snowflake.connector.",
    " snowflake.connector:",
)


def _qualified_table_name():
    configured = os.getenv("APP_LOG_TABLE", DEFAULT_LOG_TABLE)
    parts = configured.split(".")
    if len(parts) != 3 or not all(_IDENTIFIER_PATTERN.fullmatch(part) for part in parts):
        raise ValueError("APP_LOG_TABLE must be a database.schema.table identifier")
    return ".".join(parts)


class _SnowflakeLogWriter:
    def __init__(self, table_name):
        self.table_name = table_name
        queue_size = max(100, int(os.getenv("GCS_LOG_QUEUE_MAX_ITEMS", "10000")))
        self.items = queue.Queue(maxsize=queue_size)
        self.dropped_messages = 0
        self._drop_lock = threading.Lock()
        self.stop_marker = object()
        self.thread = threading.Thread(target=self._run, name="snowflake-app-log-writer", daemon=True)
        self.thread.start()

    def submit(self, created_at, stream_name, message):
        try:
            self.items.put_nowait((created_at, stream_name, message))
            return True
        except queue.Full:
            # Logging must never consume unbounded application memory.
            with self._drop_lock:
                self.dropped_messages += 1
            return False

    def close(self):
        if self.thread.is_alive():
            self.items.put(self.stop_marker)
            self.thread.join(timeout=10)

    def _run(self):
        pending = []
        while True:
            try:
                item = self.items.get(timeout=1)
            except queue.Empty:
                item = None
            stopping = item is self.stop_marker
            if item is not None and not stopping:
                pending.append(item)
            if pending and (stopping or item is None or len(pending) >= 100):
                try:
                    self._write_batch(pending)
                except Exception as exc:
                    sys.__stderr__.write(f"Snowflake application logging failed: {exc}\n")
                    sys.__stderr__.flush()
                pending.clear()
            if stopping:
                return

    def _write_batch(self, rows):
        from services.snowflake_service import SnowflakeService
        database, schema, _ = self.table_name.split(".")
        conn = SnowflakeService().connect(database=database, schema=schema)
        cursor = conn.cursor()
        try:
            cursor.executemany(
                f"INSERT INTO {self.table_name} (LOGGED_AT, STREAM, MESSAGE, HOST_NAME) VALUES (%s, %s, %s, %s)",
                [(*row, socket.gethostname()) for row in rows],
            )
            conn.commit()
        finally:
            cursor.close()
            conn.close()


class _SnowflakeLogStream:
    def __init__(self, original_stream, writer, stream_name):
        self.original_stream = original_stream
        self.writer = writer
        self.stream_name = stream_name
        self.lock = threading.RLock()
        self.pending = ""
        self.max_pending_chars = max(1024, int(os.getenv("GCS_LOG_MAX_LINE_CHARS", "65536")))
        self._gcs_snowflake_log_stream = True

    def write(self, message):
        with self.lock:
            self.original_stream.write(message)
            self.original_stream.flush()
            # Snowflake emits logs while this writer persists logs. Capturing
            # those messages would feed them back into the same queue forever.
            if threading.current_thread() is getattr(self.writer, "thread", None):
                return
            self.pending += message
            while "\n" in self.pending:
                line, self.pending = self.pending.split("\n", 1)
                self._submit(line)
            while len(self.pending) > self.max_pending_chars:
                line, self.pending = self.pending[:self.max_pending_chars], self.pending[self.max_pending_chars:]
                self._submit(line)

    def flush(self):
        with self.lock:
            self.original_stream.flush()
            if self.pending:
                self._submit(self.pending)
                self.pending = ""

    def _submit(self, line):
        # Connector diagnostics are already printed locally. Persisting them
        # through the connector itself creates a logging feedback loop.
        if line.strip() and not any(marker in line for marker in _INTERNAL_LOG_MARKERS):
            self.writer.submit(datetime.now().astimezone(), self.stream_name, line)

    def isatty(self):
        return self.original_stream.isatty()

    @property
    def encoding(self):
        return getattr(self.original_stream, "encoding", "utf-8")


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


def setup_daily_logging(log_dir=None):
    return setup_snowflake_logging()
