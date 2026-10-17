# tests/test_attempt_loop.py
import uuid

from agent.services.attempt_service import AttemptService


def test_repeated_output_detected():
    class FakeSession:
        def scalars(self, _stmt):
            class R:
                def all(inner_self):
                    return [
                        type("A", (), {"response_json": {"x": 1}, "error_message": None})(),
                        type("A", (), {"response_json": {"x": 1}, "error_message": None})(),
                        type("A", (), {"response_json": {"x": 1}, "error_message": None})(),
                    ]

            return R()

    svc = AttemptService(FakeSession())  # type: ignore[arg-type]
    fp = AttemptService.fingerprint({"x": 1})
    assert svc.repeated_output_detected(uuid.uuid4(), fp, window=3)
