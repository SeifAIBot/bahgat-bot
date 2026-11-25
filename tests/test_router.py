from brain.router import _status_of, CircuitBreaker

def test_status_classification():
    class E(Exception):
        status_code = 429
    assert _status_of(E()) == 429

def test_circuit_breaker_opens_after_3():
    cb = CircuitBreaker(threshold=3, open_seconds=60)
    assert cb.allow()
    cb.record_failure(); cb.record_failure(); cb.record_failure()
    assert not cb.allow()
    cb.record_success()
    assert cb.allow()
