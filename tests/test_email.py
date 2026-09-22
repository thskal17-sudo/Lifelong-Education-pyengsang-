from gia.notify.email import SmtpConfig, send_email


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.logged_in = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        FakeSMTP.sent.append((self.host, self.port, self.logged_in, msg))


def test_from_env_requires_host_and_to():
    assert SmtpConfig.from_env({}) is None
    cfg = SmtpConfig.from_env({"SMTP_HOST": "smtp.example.org", "EMAIL_TO": "a@x.org, b@x.org", "SMTP_USER": "u", "SMTP_PASSWORD": "p"})
    assert cfg.to == ["a@x.org", "b@x.org"] and cfg.sender == "u" and cfg.port == 587


def test_send_email_builds_multipart():
    cfg = SmtpConfig(host="smtp.example.org", port=465, user="u", password="p", sender="u@x.org", to=["a@x.org"])
    n = send_email(cfg, "[경남 강사공고] 09/21", "<p>html</p>", "text", smtp_factory=FakeSMTP)
    assert n == 1
    host, port, login, msg = FakeSMTP.sent[-1]
    assert (host, port, login) == ("smtp.example.org", 465, ("u", "p"))
    assert msg["Subject"] == "[경남 강사공고] 09/21" and "a@x.org" in msg["To"]
    parts = [p.get_content_type() for p in msg.walk()]
    assert "text/plain" in parts and "text/html" in parts
