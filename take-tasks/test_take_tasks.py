import importlib.util
import json
import os
import shutil
import tempfile
import unittest
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["TEAM_CONFIG"] = os.path.join(HERE, "..", "tests", "missing-config.toml")
NOW = 1791326000                      # 2026-10-06 22:33 UTC, last bell 20:00 UTC that day
BELL = 1791316800


def load():
    spec = importlib.util.spec_from_file_location("take_tasks", os.path.join(HERE, "take-tasks.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SeatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        tt = self.tt = load()
        tt.BELL_HOUR = 20
        tt.SEAT_GROUPS = {"A": (1, ("social", "scout")), "B": (2, ("judge", "reviewer")),
                          "C": (3, ("researcher", "investigator", "verifier")), "D": (4, ("builder", "tester")),
                          "E": (5, ("writer",))}
        tt.SEAT_OF = {p: g for g, (_, ps) in tt.SEAT_GROUPS.items() for p in ps}
        tt.GATE_DIR = os.path.join(self.tmp, "gate")
        tt.OUT_ROOT = os.path.join(self.tmp, "out")
        tt.OUT_DIR = os.path.join(tt.OUT_ROOT, "tasks")
        tt.WORK_DIR = os.path.join(self.tmp, "work")
        tt.PROPOSALS = os.path.join(tt.OUT_ROOT, "proposals")
        tt.KEYS_DIR = os.path.join(self.tmp, "keys")
        for d in (os.path.join(tt.GATE_DIR, "tasks"), tt.OUT_DIR, tt.PROPOSALS, tt.KEYS_DIR):
            os.makedirs(d)
        for g in "ABCDE":
            with open(os.path.join(tt.KEYS_DIR, g + ".env"), "w") as f:
                f.write("SEAT_KEY=key-%s\n" % g)
        self.usd = {"A": 2.5, "B": 0.0, "C": 0.04, "D": 2.6, "E": 1.0}
        self.balance_calls = []

        def balance(key):
            self.balance_calls.append(key)
            return self.usd[key[-1]]
        tt.balance = balance
        self.cards, self.calls, self.created = {}, [], []

        def hermes(*args, stdin=None):
            self.calls.append(args)
            if args[0] == "create":
                cid = "t_%04d" % (len(self.cards) + 1)
                a = dict(zip(args[2::2], args[3::2]))
                self.cards[cid] = {"task": {"id": cid, "assignee": a["--assignee"], "status": "ready",
                                            "last_failure_error": None}, "runs": []}
                self.created.append((cid, a))
                return json.dumps({"id": cid})
            if args[0] == "show":
                return json.dumps(self.cards[args[1]])
            if args[0] == "list":
                return json.dumps([c["task"] for c in self.cards.values() if c["task"]["status"] == "ready"])
            if args[0] == "reassign":
                self.cards[args[1]]["task"]["assignee"] = args[2]
                return "Reassigned"
            if args[0] == "comment":
                return "Comment added"
            raise AssertionError(args)
        tt.hermes = hermes
        self.logs = []
        tt.log = self.logs.append

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_main(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            return self.tt.main()

    def card(self, cid, assignee, runs=(), err=None):
        self.cards[cid] = {"task": {"id": cid, "assignee": assignee, "status": "ready", "last_failure_error": err},
                           "runs": [dict(r) for r in runs]}

    def walled(self, profile, ended=NOW - 300):
        return {"profile": profile, "outcome": "rate_limited", "ended_at": ended,
                "error": "pid 1 exited rate-limited (quota wall): requeued without counting a failure"}

    def task(self, tid, text):
        with open(os.path.join(self.tt.GATE_DIR, "tasks", tid + ".json"), "w") as f:
            json.dump({"id": tid, "text": text, "from": 1, "ts": "2026-10-06T22:00:00Z"}, f)

    def moves(self):
        return [(a[1], a[2]) for a in self.calls if a[0] == "reassign"]

    def test_quota_wall_card_moves_to_richest_seat(self):
        self.usd["B"] = 5.0                               # balance back above floor, but B walled this card tonight
        err = "pid 2 exited rate-limited (quota wall): requeued without counting a failure"
        self.card("t_a", "reviewer", [self.walled("reviewer")], err)
        self.card("t_old", "reviewer", [self.walled("reviewer", ended=BELL - 60)], err)   # walled before the bell
        self.card("t_ok", "scout")
        self.tt.rebalance(self.tt.seats(NOW), NOW)
        self.assertEqual(self.moves(), [("t_a", "tester")])      # research order: researcher C empty, reviewer walled
        self.assertIn(("comment", "t_a", "переназначено: место 2 пустое", "--author", "take-tasks"), self.calls)
        self.assertTrue(any("t_a seat 2 empty: reviewer -> tester" in m for m in self.logs))

    def test_english_rebalance_comment(self):
        self.tt.LOCALE = "en"
        self.card("t_a", "reviewer")
        self.tt.rebalance(self.tt.seats(NOW), NOW)
        self.assertIn(("comment", "t_a", "reassigned: seat 2 empty", "--author", "take-tasks"), self.calls)

    def test_empty_seat_card_moves_and_keeps_kind(self):
        self.card("t_j", "judge")                        # B empty: judge -> writer, reviewer
        self.card("t_r", "writer", [self.walled("judge"), {"profile": "writer", "outcome": "rate_limited",
                                                           "ended_at": NOW - 60}], "rate-limited")
        self.usd["E"] = 0.1                              # E empty too: judge kind has no seat left in its list
        self.tt.rebalance(self.tt.seats(NOW), NOW)
        self.assertEqual(self.moves(), [("t_j", "tester"), ("t_r", "tester")])   # any profile with budget, D richest

    def test_new_task_skips_empty_seat(self):
        self.task("20261006-2200-aaaa", "@reviewer разбор цифр topic")
        self.task("20261006-2201-bbbb", "почини скрипт")
        self.task("20261006-2202-cccc", "напиши пост")
        self.usd["D"] = 0.29                             # under the soft floor
        self.run_main()
        self.assertEqual([a["--assignee"] for _, a in self.created], ["scout", "scout", "writer"])
        self.assertEqual(self.created[0][1]["--max-runtime"], "45m")
        with open(os.path.join(self.tt.OUT_DIR, "20261006-2200-aaaa.role")) as f:
            self.assertEqual(f.read().strip(), "scout")

    def test_all_seats_empty_is_noop(self):
        for g in self.usd:
            self.usd[g] = 0.0
        self.card("t_a", "reviewer", [self.walled("reviewer")], "rate-limited (quota wall)")
        self.task("20261006-2200-aaaa", "почини скрипт")
        self.run_main()
        self.assertEqual(self.moves(), [])
        self.assertFalse([a for a in self.calls if a[0] == "comment"])
        self.assertEqual(self.created, [])
        self.assertIsNone(self.tt.read_word("20261006-2200-aaaa", ".state"))
        self.assertTrue(any("wait: no seat with budget" in m for m in self.logs))

    def test_cache_and_seats_file(self):
        self.tt.seats(NOW)
        self.assertEqual(len(self.balance_calls), 5)
        self.tt.seats(NOW + 300)
        self.assertEqual(len(self.balance_calls), 5)
        self.tt.seats(NOW + 601)
        self.assertEqual(len(self.balance_calls), 10)
        with open(os.path.join(self.tt.OUT_ROOT, "seats.json")) as f:
            s = json.load(f)
        self.assertEqual(s["groups"]["B"], {"seat": 2, "profiles": ["judge", "reviewer"], "usd": 0.0, "empty": True})
        self.assertEqual(s["groups"]["D"]["empty"], False)
        self.assertNotIn("key-", json.dumps(s))
        self.assertEqual(oct(os.stat(os.path.join(self.tt.OUT_ROOT, "seats.json")).st_mode & 0o777), "0o644")

    def test_no_keys_dir_changes_nothing(self):
        shutil.rmtree(self.tt.KEYS_DIR)
        self.card("t_a", "reviewer", [self.walled("reviewer")], "rate-limited")
        self.task("20261006-2200-aaaa", "@reviewer x y z")
        self.run_main()
        self.assertEqual(self.balance_calls, [])
        self.assertEqual(self.moves(), [])
        self.assertFalse([a for a in self.calls if a[0] == "list"])
        self.assertEqual(self.created[0][1]["--assignee"], "reviewer")

    def test_last_bell(self):
        self.assertEqual(self.tt.last_bell(NOW), BELL)
        self.assertEqual(self.tt.last_bell(BELL - 1), BELL - 86400)
        self.assertEqual(self.tt.last_bell(BELL), BELL)


if __name__ == "__main__":
    unittest.main()
