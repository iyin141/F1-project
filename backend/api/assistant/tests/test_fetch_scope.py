from api.assistant import fetch
from api.assistant.tests.test_fetch import DEC_HTML, FakeResp, FakeSession

OLD_REGS_HTML = """
<a href="/system/files/documents/fia_2025_formula_1_sporting_regulations_-_issue_4_-_2025-02-26.pdf">a</a>
<a href="/system/files/documents/fia_2025_formula_1_sporting_regulations_-_issue_5_-_2025-04-30.pdf">b</a>
<a href="/system/files/documents/fia_2025_formula_1_technical_regulations_-_issue_03_-_2025-04-07.pdf">c</a>
<a href="/system/files/documents/fia_2023_formula_1_sporting_regulations_-_issue_7_-_2023-10-25-v2.pdf">d</a>
<a href="/system/files/documents/fia_2023_formula_1_sporting_regulations_-_issue_8_-_2023-12-06_0.pdf">e</a>
<a href="/system/files/documents/formula_1_-_technical_regulations_-_2022_-_iss_11_-_2022-04-29.pdf">f</a>
<a href="/system/files/documents/fia_2022_formula_1_technical_regulations_-_issue_13_-_2022-08-16.pdf">g</a>
<a href="/system/files/documents/2022_formula_1_sporting_regulations_-_iss_5_-_2022-03-15.pdf">h</a>
<a href="/system/files/documents/fia_2026_formula_1_sporting_regulations_pu_-_issue_6_-_2024-06-11_1.pdf">pu, skipped</a>
"""

SEASON_HTML = """
<select><option value="0">Season</option>
<option value="/documents/championships/fia-formula-one-world-championship-14/season/season-2026-2072">SEASON 2026</option>
<option value="/documents/championships/fia-formula-one-world-championship-14/season/season-2025-2071">SEASON 2025</option></select>
<select><option value="0">Event</option>
<option value="/documents/championships/x/season/season-2025-2071/event/Abu%20Dhabi%20Grand%20Prix">Abu Dhabi</option>
<option value="/documents/championships/x/season/season-2025-2071/event/Austrian%20Grand%20Prix">Austria</option></select>
"""


def test_older_regulation_names_latest_issue_per_year():
    got = {(c.year, c.doc_type): c.url.rsplit("/", 1)[-1] for c in fetch.parse_regulations(OLD_REGS_HTML)}
    assert got[(2025, "sporting_regs")].endswith("issue_5_-_2025-04-30.pdf")
    assert got[(2025, "technical_regs")].endswith("issue_03_-_2025-04-07.pdf")
    assert "issue_8" in got[(2023, "sporting_regs")]
    assert "issue_13" in got[(2022, "technical_regs")]  # a later issue beats the other naming scheme's iss_11
    assert (2022, "sporting_regs") in got and not any(y == 2026 for y, _ in got)


def test_season_and_event_discovery_and_summons_filter():
    assert fetch.season_urls(SEASON_HTML)[2025].endswith("season-2025-2071")
    evs = fetch.event_urls(SEASON_HTML)
    assert len(evs) == 2 and evs[0].startswith("https://www.fia.com/") and evs[0].endswith("Abu%20Dhabi%20Grand%20Prix")
    assert len(fetch.parse_decisions(DEC_HTML, include_summons=False)) == 2
    assert len(fetch.parse_decisions(DEC_HTML)) == 3


def test_season_candidates_one_request_per_event():
    class S(FakeSession):
        def get(self, url, timeout=0, headers=None):
            self.calls.append(url)
            if url.endswith("/robots.txt"):
                return FakeResp(text=self.robots)
            if "/event/" not in url:
                return FakeResp(text=SEASON_HTML)
            return FakeResp(text=DEC_HTML)

    f = fetch.Fetcher(S(), delay=0)
    got = fetch.season_candidates(f, "https://www.fia.com/documents/championships/x/season/season-2025-2071")
    assert not any("page=" in c for c in f.session.calls)
    assert len(got) == 2  # decisions and notes only (no summons); the second event repeats the same PDFs: deduped


def test_get_bytes_ranged_download_retries_a_dropped_chunk():
    body = b"%PDF-1.4\n" + bytes(range(256)) * 40 + b"\n%%EOF\n"

    class Ranged(FakeSession):
        failed = False

        def get(self, url, timeout=0, headers=None):
            self.calls.append(url)
            if url.endswith("/robots.txt"):
                return FakeResp(text=self.robots)
            lo, hi = (int(x) for x in headers["Range"].split("=")[1].split("-"))
            if lo > 0 and not self.failed:  # the TLS stream dies once mid-download
                self.failed = True
                raise OSError("bad record mac")
            r = FakeResp(content=body[lo:hi + 1])
            r.status_code = 206
            r.headers = {"Content-Range": f"bytes {lo}-{min(hi, len(body) - 1)}/{len(body)}"}
            return r

    f = fetch.Fetcher(Ranged(), delay=0)
    assert f.get_bytes("https://www.fia.com/big.pdf", chunk=1000) == body
