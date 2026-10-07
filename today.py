"""Update both animated cards from public GitHub data using the job's token."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

from dateutil.relativedelta import relativedelta
from lxml import etree
import requests

ROOT = Path(__file__).resolve().parent


class GitHubError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, token: str, session=None):
        if not token:
            raise GitHubError('Set GH_TOKEN to the workflow GITHUB_TOKEN before running.')
        self.session = session or requests.Session()
        self.headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
        self.calls = 0

    def query(self, query: str, variables: dict) -> dict:
        for attempt in range(3):
            self.calls += 1
            try:
                response = self.session.post(
                    'https://api.github.com/graphql', json={'query': query, 'variables': variables},
                    headers=self.headers, timeout=(10, 60))
            except requests.RequestException:
                if attempt == 2:
                    raise GitHubError('GitHub request failed after three attempts.') from None
                time.sleep(2 ** attempt)
                continue
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                try:
                    retry_after = float(response.headers.get('Retry-After', '0'))
                except ValueError:
                    retry_after = 0
                time.sleep(min(30, max(2 ** attempt, retry_after)))
                continue
            if response.status_code == 401:
                raise GitHubError('GitHub rejected the API token (401 Bad credentials).')
            if response.status_code != 200:
                raise GitHubError(f'GitHub API returned HTTP {response.status_code}.')
            try:
                payload = response.json()
            except ValueError:
                raise GitHubError('GitHub returned invalid JSON.') from None
            if payload.get('errors'):
                messages = '; '.join(e.get('message', 'Unknown GraphQL error') for e in payload['errors'])
                raise GitHubError(f'GitHub GraphQL: {messages}')
            if not isinstance(payload.get('data'), dict):
                raise GitHubError('GitHub returned no GraphQL data.')
            return payload['data']
        raise GitHubError('GitHub retries exhausted.')


ACCOUNT_QUERY = '''query($login:String!) {
  user(login:$login) { id createdAt followers { totalCount } }
}'''
REPOS_QUERY = '''query($login:String!, $cursor:String) {
  user(login:$login) {
    repositories(first:100, after:$cursor, privacy:PUBLIC,
      ownerAffiliations:[OWNER,COLLABORATOR,ORGANIZATION_MEMBER]) {
      nodes { nameWithOwner owner { login } stargazerCount
        defaultBranchRef { target { ... on Commit { oid } } } }
      pageInfo { hasNextPage endCursor }
    }
  }
}'''
HISTORY_QUERY = '''query($owner:String!, $name:String!, $author:ID!, $head:GitObjectID!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    object(oid:$head) { ... on Commit {
      history(first:100, after:$cursor, author:{id:$author}) {
        edges { node { additions deletions } }
        pageInfo { hasNextPage endCursor }
      }
    } }
  }
}'''


def next_cursor(page: dict) -> str | None:
    if not page['hasNextPage']:
        return None
    if not page.get('endCursor'):
        raise GitHubError('GitHub pagination has no next cursor.')
    return page['endCursor']


def public_repositories(client: GitHubClient, login: str) -> list[dict]:
    repos, cursor, seen = [], None, set()
    while True:
        data = client.query(REPOS_QUERY, {'login': login, 'cursor': cursor})
        if data['user'] is None:
            raise GitHubError(f'GitHub account {login} does not exist.')
        connection = data['user']['repositories']
        repos.extend(connection['nodes'])
        cursor = next_cursor(connection['pageInfo'])
        if cursor is None:
            return repos
        if cursor in seen:
            raise GitHubError('GitHub repeated a repository pagination cursor.')
        seen.add(cursor)


def authored_history(client: GitHubClient, repo: dict, author: str) -> dict:
    branch = repo['defaultBranchRef']
    head = branch['target']['oid'] if branch else None
    result = {'head': head, 'commits': 0, 'additions': 0, 'deletions': 0}
    if head is None:
        return result
    owner, name = repo['nameWithOwner'].split('/', 1)
    cursor, seen = None, set()
    while True:
        data = client.query(HISTORY_QUERY, {'owner': owner, 'name': name, 'author': author,
                                           'head': head, 'cursor': cursor})
        repository = data['repository']
        if repository is None or repository['object'] is None:
            raise GitHubError('Repository or commit became unavailable during the update.')
        history = repository['object']['history']
        for edge in history['edges']:
            result['commits'] += 1
            result['additions'] += edge['node']['additions']
            result['deletions'] += edge['node']['deletions']
        cursor = next_cursor(history['pageInfo'])
        if cursor is None:
            return result
        if cursor in seen:
            raise GitHubError('GitHub repeated a commit pagination cursor.')
        seen.add(cursor)


def load_cache(path: Path, author: str) -> dict:
    try:
        data = json.loads(path.read_text())
        if data.get('schema') != 1 or data.get('author') != author or not isinstance(data.get('repos'), dict):
            return {}
        return data['repos']
    except (OSError, ValueError, AttributeError):
        return {}


def valid_entry(entry: object, head: str | None) -> bool:
    return (isinstance(entry, dict) and entry.get('head') == head
            and all(type(entry.get(k)) is int and entry[k] >= 0
                    for k in ('commits', 'additions', 'deletions')))


def collect_stats(client: GitHubClient, login: str, cache_path: Path, refresh=False):
    account = client.query(ACCOUNT_QUERY, {'login': login})['user']
    if account is None:
        raise GitHubError(f'GitHub account {login} does not exist.')
    repos = public_repositories(client, login)
    old_cache = {} if refresh else load_cache(cache_path, account['id'])
    entries = {}
    totals = {'commits': 0, 'additions': 0, 'deletions': 0}
    owned = [r for r in repos if r['owner']['login'].lower() == login.lower()]
    for repo in repos:
        key = hashlib.sha256(repo['nameWithOwner'].encode()).hexdigest()
        branch = repo['defaultBranchRef']
        head = branch['target']['oid'] if branch else None
        entry = old_cache.get(key)
        if not valid_entry(entry, head):
            entry = authored_history(client, repo, account['id'])
        entries[key] = entry
        for field in totals:
            totals[field] += entry[field]
    created = dt.datetime.fromisoformat(account['createdAt'].replace('Z', '+00:00'))
    age = relativedelta(dt.datetime.now(dt.timezone.utc), created)
    uptime = ', '.join(f'{n} {unit}{"s" if n != 1 else ""}'
                       for n, unit in ((age.years, 'year'), (age.months, 'month'), (age.days, 'day')))
    stats = {'age_data': uptime, 'repo_data': len(owned), 'contrib_data': len(repos),
             'star_data': sum(r['stargazerCount'] for r in owned),
             'follower_data': account['followers']['totalCount'], 'commit_data': totals['commits'],
             'loc_data': totals['additions'] - totals['deletions'],
             'loc_add': totals['additions'], 'loc_del': totals['deletions']}
    cache = {'schema': 1, 'author': account['id'], 'repos': entries}
    return stats, cache


def render_card(path: Path, stats: dict) -> bytes:
    tree = etree.parse(str(path), etree.XMLParser(resolve_entities=False, no_network=True))
    widths = {'age_data': 40, 'commit_data': 22, 'star_data': 14, 'repo_data': 6,
              'follower_data': 10, 'loc_data': 9, 'loc_del': 7}
    root = tree.getroot()
    for key, value in stats.items():
        node = root.find(f".//*[@id='{key}']")
        if node is None:
            raise ValueError(f'{path.name} is missing the required stat ID {key}.')
        node.text = f'{value:,}' if isinstance(value, int) else str(value)
        dots = root.find(f".//*[@id='{key}_dots']")
        if dots is not None and key in widths:
            count = max(0, widths[key] - len(node.text))
            dots.text = {0: '', 1: ' ', 2: '. '}.get(count, ' ' + '.' * count + ' ')
    return etree.tostring(tree, encoding='utf-8', xml_declaration=True)


def atomic_write(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}.')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT)
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    login = os.environ.get('USER_NAME', 'atulhacks')
    client = GitHubClient(os.environ.get('GH_TOKEN') or os.environ.get('ACCESS_TOKEN', ''))
    cache_path = args.output_dir / 'cache/public-stats.json'
    stats, cache = collect_stats(client, login, cache_path, args.refresh)
    # Validate both SVGs before touching either; keep motion and geometry intact.
    cards = [(args.output_dir / n, render_card(args.output_dir / n, stats))
             for n in ('dark_mode.svg', 'light_mode.svg')]
    for path, content in cards:
        atomic_write(path, content)
    atomic_write(cache_path, (json.dumps(cache, indent=2, sort_keys=True) + '\n').encode())
    print(f'Updated public stats: {stats["repo_data"]} owned repos, '
          f'{stats["commit_data"]} authored commits; {client.calls} API requests.')


if __name__ == '__main__':
    try:
        main()
    except (GitHubError, ValueError, OSError) as error:
        raise SystemExit(f'Profile update failed: {error}') from None
