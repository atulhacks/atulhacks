import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from lxml import etree
import requests
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import today


def repo(name='atulhacks/demo', head='abc', stars=1):
    return {'nameWithOwner': name, 'owner': {'login': name.split('/')[0]},
            'stargazerCount': stars, 'defaultBranchRef': {'target': {'oid': head}} if head else None}


def page(nodes, cursor=None):
    return {'user': {'repositories': {'nodes': nodes, 'pageInfo':
            {'hasNextPage': cursor is not None, 'endCursor': cursor}}}}


def history(additions=5, deletions=2, cursor=None):
    return {'repository': {'object': {'history': {'edges': [{'node':
            {'additions': additions, 'deletions': deletions}}], 'pageInfo':
            {'hasNextPage': cursor is not None, 'endCursor': cursor}}}}}


class UpdaterTests(unittest.TestCase):
    def test_missing_token_is_clear(self):
        with self.assertRaisesRegex(today.GitHubError, 'GH_TOKEN'):
            today.GitHubClient('')

    def test_bad_token_is_not_logged(self):
        session = Mock()
        session.post.return_value.status_code = 401
        client = today.GitHubClient('secret-value', session)
        with self.assertRaisesRegex(today.GitHubError, '401 Bad credentials') as error:
            client.query('query', {})
        self.assertNotIn('secret-value', str(error.exception))
        self.assertEqual(session.post.call_args.kwargs['timeout'], (10, 60))

    def test_graphql_errors_on_http_200(self):
        session = Mock()
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {'errors': [{'message': 'Resource unavailable'}]}
        with self.assertRaisesRegex(today.GitHubError, 'Resource unavailable'):
            today.GitHubClient('token', session).query('query', {})

    def test_invalid_json(self):
        session = Mock()
        session.post.return_value.status_code = 200
        session.post.return_value.json.side_effect = ValueError()
        with self.assertRaisesRegex(today.GitHubError, 'invalid JSON'):
            today.GitHubClient('token', session).query('query', {})

    @patch('today.time.sleep')
    def test_transport_retry_is_bounded(self, sleep):
        session = Mock()
        session.post.side_effect = requests.Timeout()
        with self.assertRaisesRegex(today.GitHubError, 'three attempts'):
            today.GitHubClient('token', session).query('query', {})
        self.assertEqual(session.post.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    @patch('today.time.sleep')
    def test_transient_http_retry(self, sleep):
        bad, good = Mock(status_code=503, headers={}), Mock(status_code=200)
        good.json.return_value = {'data': {'user': 'ok'}}
        session = Mock()
        session.post.side_effect = [bad, good]
        self.assertEqual(today.GitHubClient('token', session).query('query', {}), {'user': 'ok'})
        sleep.assert_called_once()

    def test_repo_pagination_includes_every_page(self):
        client = Mock()
        client.query.side_effect = [page([repo()], 'next'), page([repo('atulhacks/other')])]
        self.assertEqual(len(today.public_repositories(client, 'atulhacks')), 2)
        self.assertEqual(client.query.call_args.args[1]['cursor'], 'next')
        self.assertIn('privacy:PUBLIC', today.REPOS_QUERY)

    def test_repeated_cursor_fails(self):
        client = Mock()
        client.query.side_effect = [page([], 'same'), page([], 'same')]
        with self.assertRaisesRegex(today.GitHubError, 'repeated'):
            today.public_repositories(client, 'atulhacks')

    def test_empty_repository_has_zero_tuple_equivalent(self):
        client = Mock()
        result = today.authored_history(client, repo(head=None), 'author')
        self.assertEqual(result, {'head': None, 'commits': 0, 'additions': 0, 'deletions': 0})
        client.query.assert_not_called()

    def test_authored_history_pagination_pins_the_head(self):
        client = Mock()
        client.query.side_effect = [history(cursor='next'), history(7, 3)]
        result = today.authored_history(client, repo(), 'author')
        self.assertEqual(result, {'head': 'abc', 'commits': 2, 'additions': 12, 'deletions': 5})
        self.assertEqual(client.query.call_args.args[1]['author'], 'author')
        self.assertEqual(client.query.call_args.args[1]['head'], 'abc')

    def test_disappearing_history_fails_without_partial_totals(self):
        client = Mock()
        client.query.return_value = {'repository': None}
        with self.assertRaises(today.GitHubError):
            today.authored_history(client, repo(), 'author')

    def test_cache_validity_checks_head_and_types(self):
        entry = {'head': 'abc', 'commits': 1, 'additions': 5, 'deletions': 2}
        self.assertTrue(today.valid_entry(entry, 'abc'))
        self.assertFalse(today.valid_entry(entry, 'force-pushed'))
        self.assertFalse(today.valid_entry({**entry, 'commits': True}, 'abc'))
        self.assertFalse(today.valid_entry({'head': 'abc'}, 'abc'))

    def test_cache_order_changes_and_deleted_repos(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'cache.json'
            key = today.hashlib.sha256(b'atulhacks/demo').hexdigest()
            path.write_text(json.dumps({'schema': 1, 'author': 'author', 'repos': {
                key: {'head': 'abc', 'commits': 2, 'additions': 9, 'deletions': 3},
                'deleted': {'head': 'old', 'commits': 999, 'additions': 999, 'deletions': 0}}}))
            client = Mock()
            client.query.side_effect = [
                {'user': {'id': 'author', 'createdAt': '2021-01-01T00:00:00Z', 'followers': {'totalCount': 11}}},
                page([repo('other/empty', None, 20), repo(stars=3)])]
            stats, cache = today.collect_stats(client, 'atulhacks', path)
            self.assertEqual(stats['repo_data'], 1)
            self.assertEqual(stats['contrib_data'], 2)
            self.assertEqual(stats['star_data'], 3)
            self.assertEqual(stats['commit_data'], 2)
            self.assertEqual(stats['loc_data'], 6)
            self.assertNotIn('deleted', cache['repos'])
            self.assertEqual(client.query.call_count, 2)

    def test_corrupt_cache_rebuilds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'cache.json'
            for value in ('not json', '[]', '{"schema":1,"author":"other","repos":{}}'):
                path.write_text(value)
                self.assertEqual(today.load_cache(path, 'author'), {})

    def test_render_preserves_motion_and_geometry(self):
        stats = {'age_data': '5 years, 6 months, 28 days', 'repo_data': 14, 'contrib_data': 14,
                 'star_data': 10, 'follower_data': 11, 'commit_data': 101,
                 'loc_data': 25000, 'loc_add': 30000, 'loc_del': 5000}
        for name in ('dark_mode.svg', 'light_mode.svg'):
            path = today.ROOT/name
            before = etree.parse(str(path)).getroot()
            after = etree.fromstring(today.render_card(path, stats))
            self.assertEqual(before.get('viewBox'), after.get('viewBox'))
            self.assertEqual(before.find('{*}style').text, after.find('{*}style').text)
            self.assertEqual(after.get('data-motion'), 'clover-terminal-v1')
            self.assertEqual(after.find(".//*[@id='repo_data']").text, '14')
            self.assertEqual(after.find(".//*[@id='loc_data']").text, '25,000')

    def test_missing_svg_id_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'broken.svg'
            path.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
            with self.assertRaisesRegex(ValueError, 'missing the required stat ID'):
                today.render_card(path, {'repo_data': 14})

    def test_atomic_write_creates_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'cache'/ 'stats.json'
            today.atomic_write(path, b'{}')
            self.assertEqual(path.read_bytes(), b'{}')
            self.assertEqual(list(path.parent.iterdir()), [path])

if __name__ == '__main__':
    unittest.main()
