import hashlib

import pytest

from api.assistant import fetch
from api.assistant.models import DocumentSource

PDF = b"%PDF-1.4\nbody\n%%EOF\n"

REGS_HTML = """
<a href="https://www.fia.com/system/files/documents/fia_2026_f1_regulations_-_section_b_sporting_-_iss_08_-_2026-08-05_7.pdf">old</a>
<a href="https://www.fia.com/system/files/documents/fia_2026_f1_regulations_-_section_b_sporting_-_iss_09_-_2026-10-01.pdf">new</a>
<a href="https://www.fia.com/system/files/documents/fia_2026_f1_regulations_-_section_c_technical_-_iss_21_-_2026-10-19.pdf">tech</a>
<a href="https://www.fia.com/system/files/documents/fia_2026_f1_regulations_-_section_a_general_provisions_-_iss_03_-_2026-06-25.pdf">gen</a>
<a href="/system/files/documents/something_else.pdf">other</a>
"""
DEC_HTML = """
<a href="/system/files/decision-document/2026_las_vegas_grand_prix_-_infringement_-_car_11_-_causing_a_collision_with_car_51.pdf">a</a>
<a href="/system/files/decision-document/2026_las_vegas_grand_prix_-_summons_-_car_3_-_alleged_erratic_driving_in_turn_16.pdf">b</a>
<a href="/system/files/decision-document/2026_las_vegas_grand_prix_-_race_directors_competition_notes_v2.pdf">c</a>
<a href="/system/files/decision-document/2026_las_vegas_grand_prix_-_final_race_classification.pdf">d</a>
"""


def test_regulations_latest_issue_per_section():
    c = {x.title.split(" Section ")[1][0]: x for x in fetch.parse_regulations(REGS_HTML)}
    assert set(c) == {"B", "C", "A"}
    assert "iss_09" in c["B"].url and c["B"].doc_type == "sporting_regs"
    assert c["C"].doc_type == "technical_regs" and c["A"].doc_type == "other_regs"


def test_decisions_typed_and_results_skipped():
    got = {x.url.rsplit("/", 1)[-1]: x for x in fetch.parse_decisions(DEC_HTML)}
    assert len(got) == 3  # the classification sheet is not stewards material
    inf = got["2026_las_vegas_grand_prix_-_infringement_-_car_11_-_causing_a_collision_with_car_51.pdf"]
    assert (inf.doc_type, inf.year, inf.race) == ("stewards_decision", 2026, "las vegas grand prix")
    assert got["2026_las_vegas_grand_prix_-_race_directors_competition_notes_v2.pdf"].doc_type == "event_notes"


class FakeResp:
    def __init__(self, content=b"", text="", status=200):
        self.content, self.text, self.status_code = content, text, status
        self.headers = {}

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, robots="User-agent: *\nDisallow: /user/\n"):
        self.headers, self.calls, self.robots = {}, [], robots

    def get(self, url, timeout=0):
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            return FakeResp(text=self.robots)
        return FakeResp(content=PDF)


def test_fetcher_rate_limits_and_obeys_robots():
    sleeps, now = [], [0.0]
    f = fetch.Fetcher(FakeSession(), delay=10, sleep=lambda s: (sleeps.append(s), now.__setitem__(0, now[0] + s)),
                      clock=lambda: now[0])
    f.get("https://www.fia.com/a.pdf")
    f.get("https://www.fia.com/b.pdf")
    assert sleeps and all(abs(s - 10) < 1e-6 for s in sleeps)  # robots.txt, a, b spaced by the Crawl-delay
    assert "F1ControlRoomCorpusFetcher" in f.session.headers["User-Agent"]
    with pytest.raises(PermissionError):
        f.get("https://www.fia.com/user/login/")


@pytest.mark.django_db
def test_store_pdf_dedupes_by_sha256(tmp_path):
    a = fetch.Candidate("https://x/a.pdf", "stewards_decision", 2026, "r", "t")
    b = fetch.Candidate("https://x/copy-of-a.pdf", "stewards_decision", 2026, "r", "t")
    s1, new1 = fetch.store_pdf(a, PDF, tmp_path)
    s2, new2 = fetch.store_pdf(b, PDF, tmp_path)
    assert new1 and not new2 and s1.pk == s2.pk
    assert DocumentSource.objects.count() == 1 and s1.sha256 == hashlib.sha256(PDF).hexdigest()
    assert (tmp_path / s1.file_path).read_bytes() == PDF
    with pytest.raises(ValueError):
        fetch.store_pdf(fetch.Candidate("https://x/h.html", "stewards_decision", 2026), b"<html>", tmp_path)
    with pytest.raises(ValueError):  # truncated download (no %%EOF): the schannel failure seen in practice
        fetch.store_pdf(fetch.Candidate("https://x/t.pdf", "stewards_decision", 2026), b"%PDF-1.4\nhalf", tmp_path)


@pytest.mark.django_db
def test_fetch_candidate_skips_known_url(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARDS_DATA_DIR", str(tmp_path))
    sess = FakeSession()
    f = fetch.Fetcher(sess, delay=0)
    cand = fetch.Candidate("https://www.fia.com/x.pdf", "stewards_decision", 2026)
    assert fetch.fetch_candidate(f, cand)[1] == "stored"
    n = len(sess.calls)
    assert fetch.fetch_candidate(f, cand)[1] == "known"
    assert len(sess.calls) == n  # no second download
