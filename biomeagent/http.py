"""Small HTTP client. Tools depend on this, and tests pass a fake."""

import httpx

TIMEOUT_SECONDS = 20


class HttpError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


class HttpClient:
    def __init__(self, timeout=TIMEOUT_SECONDS):
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)

    def get_text(self, url, params=None):
        return self._send(url, params).text

    def get_json(self, url, params=None):
        response = self._send(url, params)
        return response.json()

    def _send(self, url, params):
        if params:
            params = {key: value for key, value in params.items() if value is not None}
        try:
            response = self._client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise HttpError("timed out") from exc
        except httpx.HTTPError as exc:
            raise HttpError(str(exc)) from exc
        if response.status_code == 429:
            raise HttpError("hourly cap")
        if response.status_code >= 400:
            raise HttpError(f"HTTP {response.status_code}")
        return response
