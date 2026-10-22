import json

from synapse.env import load_secrets_manager


class FakeSecrets:
    def __init__(self, value: str | Exception):
        self.value, self.asked = value, []

    def get_secret_value(self, SecretId):
        self.asked.append(SecretId)
        if isinstance(self.value, Exception):
            raise self.value
        return {"SecretString": self.value}


def test_not_configured_does_nothing(monkeypatch):
    monkeypatch.delenv("SYNAPSE_SECRETS_ID", raising=False)
    assert load_secrets_manager(FakeSecrets("{}")) == []


def test_sets_missing_variables_only(monkeypatch):
    monkeypatch.setenv("SYNAPSE_SECRETS_ID", "synapsesupply/runtime")
    monkeypatch.setenv("AICORE_CLIENT_ID", "already-set")
    monkeypatch.delenv("AICORE_CLIENT_SECRET", raising=False)
    fake = FakeSecrets(json.dumps({"AICORE_CLIENT_ID": "from-secret", "AICORE_CLIENT_SECRET": "s3cret", "N": 1}))
    assert load_secrets_manager(fake) == ["AICORE_CLIENT_SECRET"]
    assert fake.asked == ["synapsesupply/runtime"]
    import os
    assert os.environ["AICORE_CLIENT_ID"] == "already-set" and os.environ["AICORE_CLIENT_SECRET"] == "s3cret"
    monkeypatch.delenv("AICORE_CLIENT_SECRET")


def test_failures_do_not_raise(monkeypatch):
    monkeypatch.setenv("SYNAPSE_SECRETS_ID", "x")
    assert load_secrets_manager(FakeSecrets(RuntimeError("AccessDenied"))) == []
    assert load_secrets_manager(FakeSecrets("[1, 2]")) == []
    assert load_secrets_manager(FakeSecrets("not json")) == []
