"""XDF writer thread-safety test."""

import threading

from tests.capture_tests.xdf.support import _iter_chunks


class TestThreadSafety:
    def test_concurrent_writes_produce_valid_file(self, writer):
        def write_eeg():
            for i in range(20):
                writer.write_samples("EEG", [[float(i)] * 8], [float(i)])

        def write_hrv():
            for i in range(5):
                writer.write_samples("HRV", [[float(800 + i)]], [float(i)])

        def write_eda():
            for i in range(10):
                writer.write_samples("EDA", [[float(5 + i * 0.1)]], [float(i)])

        threads = [
            threading.Thread(target=write_eeg),
            threading.Thread(target=write_hrv),
            threading.Thread(target=write_eda),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        writer.close()

        assert writer.sample_counts["EEG"] == 20
        assert writer.sample_counts["HRV"] == 5
        assert writer.sample_counts["EDA"] == 10

        raw = writer.path.read_bytes()
        chunk_count = sum(1 for _ in _iter_chunks(raw))
        # magic(skip) + FileHeader + 5×StreamHeader + ≥1 Samples + 5×StreamFooter
        assert chunk_count >= 11
