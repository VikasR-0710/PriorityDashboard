import io
import queue
import threading
import unittest

from config.logging_setup import _SnowflakeLogStream, _SnowflakeLogWriter


class LoggingMemorySafetyTests(unittest.TestCase):
    def test_queue_drops_messages_instead_of_growing_without_limit(self):
        writer = _SnowflakeLogWriter.__new__(_SnowflakeLogWriter)
        writer.items = queue.Queue(maxsize=1)
        writer.dropped_messages = 0
        writer._drop_lock = threading.Lock()

        self.assertTrue(writer.submit(None, "stdout", "first"))
        self.assertFalse(writer.submit(None, "stdout", "second"))
        self.assertEqual(writer.items.qsize(), 1)
        self.assertEqual(writer.dropped_messages, 1)

    def test_writer_thread_logs_are_not_fed_back_into_its_queue(self):
        submissions = []

        class Writer:
            thread = threading.current_thread()

            @staticmethod
            def submit(*args):
                submissions.append(args)

        original = io.StringIO()
        stream = _SnowflakeLogStream(original, Writer(), "stderr")
        stream.write("Snowflake connector internal log\n")

        self.assertEqual(original.getvalue(), "Snowflake connector internal log\n")
        self.assertEqual(submissions, [])

    def test_application_logs_are_still_submitted(self):
        submissions = []

        class Writer:
            thread = object()

            @staticmethod
            def submit(*args):
                submissions.append(args)

        stream = _SnowflakeLogStream(io.StringIO(), Writer(), "stdout")
        stream.write("application log\n")
        self.assertEqual(len(submissions), 1)

    def test_connector_logs_from_helper_threads_are_not_enqueued(self):
        submissions = []

        class Writer:
            thread = object()

            @staticmethod
            def submit(*args):
                submissions.append(args)

        original = io.StringIO()
        stream = _SnowflakeLogStream(original, Writer(), "stderr")
        message = "2026-08-09 INFO snowflake.connector.connection: Connecting\n"
        stream.write(message)
        self.assertEqual(original.getvalue(), message)
        self.assertEqual(submissions, [])


if __name__ == "__main__":
    unittest.main()
