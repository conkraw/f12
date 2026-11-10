"""Separate encrypted, per-event technical import journal in the private repo.

No clinical source, room, name, MRN, date of birth, medication values, exception
body or stack locals are accepted. Unique create-only records avoid a shared
read/modify/write log race. Review-state edits require the observed GitHub SHA.
"""
from __future__ import annotations
import base64
from copy import deepcopy
from datetime import datetime, timezone
import json
import re
import uuid
from cryptography.fernet import Fernet, InvalidToken
from github_store import GitHubVault, StorageError, ConflictError
from import_review import validate_diagnostic

PREFIX = 'encrypted-data/import-errors'
APP_VERSION = '6.48'
MAX_RECORD_BYTES = 100000
NAME = re.compile(r'^\d{8}T\d{6}Z-[0-9a-f]{32}\.enc$')


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def new_error_event(diagnostics: list[dict]) -> dict:
    stamp = now_utc()
    event = dict(schema=1, id=uuid.uuid4().hex, created_at=stamp, updated_at=stamp,
                 app_version=APP_VERSION, diagnostics=deepcopy(diagnostics[:100]), status='open')
    validate_event(event)
    return event


def validate_event(event: dict) -> None:
    if not isinstance(event, dict) or set(event) != {'schema', 'id', 'created_at', 'updated_at', 'app_version', 'diagnostics', 'status'}:
        raise ValueError('The technical error record is invalid.')
    if event['schema'] != 1 or not isinstance(event['id'], str) or not re.fullmatch(r'[0-9a-f]{32}', event['id']):
        raise ValueError('The technical error record identifier is invalid.')
    if not isinstance(event['app_version'], str) or not re.fullmatch(r'\d{1,3}\.\d{1,3}', event['app_version']):
        raise ValueError('The technical error version is invalid.')
    if event['status'] not in ('open', 'resolved'):
        raise ValueError('The error review status is invalid.')
    for key in ('created_at', 'updated_at'):
        if not isinstance(event[key], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00', event[key]):
            raise ValueError('The technical error timestamp is invalid.')
        datetime.fromisoformat(event[key])
    if not isinstance(event['diagnostics'], list) or not 1 <= len(event['diagnostics']) <= 100:
        raise ValueError('The technical error details are invalid.')
    for item in event['diagnostics']:
        validate_diagnostic(item)


def event_path(event: dict) -> str:
    validate_event(event)
    date = datetime.fromisoformat(event['created_at'])
    return PREFIX + '/' + date.strftime('%Y-%m') + '/' + date.strftime('%Y%m%dT%H%M%SZ') + '-' + event['id'] + '.enc'


class ErrorJournal:
    def __init__(self, vault: GitHubVault):
        self.vault = vault

    def _decode(self, response, expected_path: str) -> tuple[dict, str]:
        data = self.vault._json(response)
        if data.get('type') != 'file' or data.get('encoding') != 'base64' or not data.get('sha'):
            raise StorageError('The encrypted error record could not be read.')
        try:
            content = data['content']
            if not isinstance(content, str) or len(content) > MAX_RECORD_BYTES * 2:
                raise ValueError
            token = base64.b64decode(''.join(content.split()), validate=True)
            if len(token) > MAX_RECORD_BYTES:
                raise ValueError
            event = json.loads(Fernet(self.vault.key.encode('ascii')).decrypt(token))
            validate_event(event)
            if event_path(event) != expected_path:
                raise ValueError
        except (ValueError, TypeError, KeyError, InvalidToken, UnicodeError):
            raise StorageError('An encrypted error record failed validation. Nothing was overwritten.') from None
        return event, data['sha']

    def _payload(self, event: dict, sha: str | None = None) -> dict:
        validate_event(event)
        token = Fernet(self.vault.key.encode('ascii')).encrypt(
            json.dumps(event, sort_keys=True, separators=(',', ':')).encode('utf-8'))
        if len(token) > MAX_RECORD_BYTES:
            raise StorageError('The technical error record is too large to save.')
        data = dict(message='Update encrypted import review record', branch=self.vault.config.branch,
                    content=base64.b64encode(token).decode('ascii'))
        if sha:
            data['sha'] = sha
        return data

    def save_new(self, event: dict) -> str:
        """Create-only, with idempotent retry after an uncertain network result."""
        validate_event(event)
        self.vault._check_repo()
        path = event_path(event)
        payload = self._payload(event)
        for attempt in range(2):
            response = self.vault._request('PUT', '/contents/' + path, json=payload)
            if response.status_code in (200, 201):
                sha = self.vault._json(response).get('content', {}).get('sha')
                if sha:
                    return sha
                raise StorageError('Error-log saving was not confirmed. Retry from Import errors.')
            if response.status_code not in (409, 422):
                raise StorageError('Error-log saving failed. Your handoff changes are still available.')
            current = self.vault._request('GET', '/contents/' + path, params={'ref': self.vault.config.branch})
            if current.status_code == 200:
                existing, sha = self._decode(current, path)
                # A reviewer may already have resolved this exact event.
                if all(existing[k] == event[k] for k in ('id', 'created_at', 'app_version', 'diagnostics')):
                    return sha
                raise ConflictError('An error record with this identifier differs. Nothing was overwritten.')
            if current.status_code != 404:
                raise StorageError('The error-log retry could not be checked.')
            # A concurrent branch update may have caused a 409 without creating
            # this unique file. Retry once, still without overwriting a file.
        raise StorageError('Error-log saving was not confirmed. Retry from Import errors.')

    def load_month(self, month: str, limit: int = 50) -> tuple[list[dict], list[str]]:
        if not re.fullmatch(r'\d{4}-\d{2}', month):
            raise StorageError('Enter the error-log month as YYYY-MM.')
        try:
            datetime.strptime(month, '%Y-%m')
        except ValueError:
            raise StorageError('The error-log month is invalid.') from None
        if type(limit) is not int or not 1 <= limit <= 100:
            raise StorageError('The error-log page size is invalid.')
        self.vault._check_repo()
        directory = PREFIX + '/' + month
        response = self.vault._request('GET', '/contents/' + directory, params={'ref': self.vault.config.branch})
        if response.status_code == 404:
            return [], []
        if response.status_code != 200:
            raise StorageError('The shared error log could not be loaded.')
        try:
            listing = response.json()
            if not isinstance(listing, list):
                raise ValueError
        except ValueError:
            raise StorageError('The error-log directory response is invalid.') from None
        candidates = [row['name'] for row in listing if isinstance(row, dict)
                      and row.get('type') == 'file' and isinstance(row.get('name'), str)
                      and NAME.fullmatch(row['name'])]
        candidates.sort(reverse=True)
        notices = []
        if len(listing) >= 1000:
            notices.append('Shared storage may have truncated this monthly directory. The listing may be incomplete.')
        if len(candidates) > limit:
            notices.append('Showing the newest ' + str(limit) + ' records from this listing. Older records remain in shared storage.')
        records = []
        for name in candidates[:limit]:
            path = directory + '/' + name
            response = self.vault._request('GET', '/contents/' + path, params={'ref': self.vault.config.branch})
            if response.status_code != 200:
                notices.append('A listed error record could not be loaded.')
                continue
            try:
                record, sha = self._decode(response, path)
            except StorageError:
                notices.append('A listed error record could not be decrypted or validated.')
                continue
            records.append({'record': record, 'sha': sha})
        return records, list(dict.fromkeys(notices))

    def set_status(self, event: dict, expected_sha: str, status: str) -> dict:
        validate_event(event)
        if status not in ('open', 'resolved') or not isinstance(expected_sha, str) or not expected_sha:
            raise StorageError('The error review update is invalid.')
        self.vault._check_repo()
        updated = deepcopy(event)
        updated.update(status=status, updated_at=now_utc())
        response = self.vault._request('PUT', '/contents/' + event_path(updated),
                                      json=self._payload(updated, expected_sha))
        if response.status_code in (409, 422):
            raise ConflictError('Another team member may have reviewed this error. Refresh the log before retrying.')
        if response.status_code not in (200, 201):
            raise StorageError('The error review change was not confirmed.')
        sha = self.vault._json(response).get('content', {}).get('sha')
        if not sha:
            raise StorageError('The error review change was not confirmed. Refresh the log.')
        return {'record': updated, 'sha': sha}
