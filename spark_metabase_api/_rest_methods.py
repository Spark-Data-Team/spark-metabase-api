import requests

DEFAULT_TIMEOUT = 30


def _client(self):
    # Created lazily for backward-compat with subclasses constructed
    # before _http existed (it is normally set in __init__).
    if not hasattr(self, "_http") or self._http is None:
        self._http = requests.Session()
    return self._http


def get(self, endpoint, *args, **kwargs):
    self.validate_session()
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    res = _client(self).get(
        self.domain + endpoint, headers=self.header, **kwargs, auth=self.auth
    )
    if "raw" in args:
        return res
    return res.json() if res.ok else False


def post(self, endpoint, *args, **kwargs):
    self.validate_session()
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    res = _client(self).post(
        self.domain + endpoint, headers=self.header, **kwargs, auth=self.auth
    )
    if "raw" in args:
        return res
    return res.json() if res.ok else False


def put(self, endpoint, *args, **kwargs):
    """Used for updating objects (cards, dashboards, ...)"""
    self.validate_session()
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    res = _client(self).put(
        self.domain + endpoint, headers=self.header, **kwargs, auth=self.auth
    )
    if "raw" in args:
        return res
    return res.status_code


def delete(self, endpoint, *args, **kwargs):
    self.validate_session()
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    res = _client(self).delete(
        self.domain + endpoint, headers=self.header, **kwargs, auth=self.auth
    )
    if "raw" in args:
        return res
    return res.status_code
