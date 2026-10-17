from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
import build_cards
import today

CARDS = ('dark_mode.svg', 'light_mode.svg')
STAT_IDS = ('age_data', 'repo_data', 'contrib_data', 'star_data', 'follower_data',
            'commit_data', 'loc_data', 'loc_add', 'loc_del')


def terminal_rows(svg: bytes):
    root = etree.fromstring(svg)
    return [''.join(t.itertext()) for t in root.iter('{*}text')
            if t.get('class') == 'row' and float(t.get('x')) == build_cards.TERM_X]


class CardTests(unittest.TestCase):
    def test_cards_carry_every_stat_id(self):
        for name in CARDS:
            root = etree.parse(str(ROOT / name)).getroot()
            self.assertEqual(root.get('data-motion'), build_cards.VERSION)
            for key in STAT_IDS:
                self.assertIsNotNone(root.find(f".//*[@id='{key}']"), f'{name} lacks {key}')

    def test_no_scripts_images_or_network(self):
        for name in CARDS:
            text = (ROOT / name).read_text()
            root = etree.fromstring(text.encode())
            self.assertFalse(root.findall('.//{*}script'))
            self.assertFalse(root.findall('.//{*}image'))
            self.assertNotIn('http://', text.replace('http://www.w3.org/2000/svg', ''))
            self.assertNotIn('https://', text)
            self.assertIn('prefers-reduced-motion', text)

    def test_generator_is_idempotent(self):
        before = [(ROOT / n).read_bytes() for n in CARDS]
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            (tmp / 'assets').mkdir()
            shutil.copy(ROOT / 'assets/clover.txt', tmp / 'assets/clover.txt')
            shutil.copy(ROOT / 'dark_mode.svg', tmp / 'dark_mode.svg')
            original_root = build_cards.ROOT
            build_cards.ROOT = tmp
            try:
                build_cards.main(tmp)
            finally:
                build_cards.ROOT = original_root
            self.assertEqual(before, [(tmp / n).read_bytes() for n in CARDS])

    def test_rows_stay_aligned_after_stat_updates(self):
        """The updater must keep every leader row exactly COLS characters wide."""
        cases = [
            {'age_data': '1 year, 1 month, 1 day', 'repo_data': 1, 'contrib_data': 1, 'star_data': 0,
             'follower_data': 1, 'commit_data': 1, 'loc_data': 1, 'loc_add': 1, 'loc_del': 0},
            {'age_data': '12 years, 11 months, 30 days', 'repo_data': 999, 'contrib_data': 999,
             'star_data': 12345, 'follower_data': 9999, 'commit_data': 123456,
             'loc_data': 9876543, 'loc_add': 9999999, 'loc_del': 123456},
        ]
        for name in CARDS:
            for stats in cases:
                svg = today.render_card(ROOT / name, stats)
                for row in terminal_rows(svg):
                    if '....' in row or row.startswith('─'):
                        self.assertEqual(len(row), build_cards.COLS, repr(row))

    def test_churn_bar_tracks_additions(self):
        stats = {'age_data': '1 day', 'repo_data': 1, 'contrib_data': 1, 'star_data': 1,
                 'follower_data': 1, 'commit_data': 1, 'loc_data': 0, 'loc_add': 50, 'loc_del': 50}
        root = etree.fromstring(today.render_card(ROOT / 'dark_mode.svg', stats))
        add, rem = root.find(".//*[@id='loc_bar_add']").text, root.find(".//*[@id='loc_bar_del']").text
        self.assertEqual(len(add), len(rem))
        self.assertEqual(len(add) + len(rem), build_cards.BAR)


if __name__ == '__main__':
    unittest.main()
