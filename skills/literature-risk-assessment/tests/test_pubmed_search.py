"""pubmed_search: hermetic tests (no network) for the PR-1 retrieval-robustness additions —
XML efetch parsing, NCBI identity params, the content-addressed cache, and HTTP backoff.
"""

from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

# Real import (registers in sys.modules) — pubmed_search defines a module-level frozen dataclass, which
# under Python 3.14 needs its module present in sys.modules to resolve; load_module (which deliberately
# does NOT register) trips that. This mirrors how ground_axis imports it.
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import pubmed_search as ps  # noqa: E402

# A minimal but realistic efetch XML set: a STRUCTURED abstract (labeled sections + inline <i> markup in
# the title), a plain abstract dated via MedlineDate, and a malformed record with no PMID (must be skipped).
_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID Version="1">111</PMID>
      <Article>
        <Journal><Title>Nature Cancer</Title>
          <JournalIssue><PubDate><Year>2021</Year></PubDate></JournalIssue>
        </Journal>
        <ArticleTitle>Mirvetuximab and <i>FOLR1</i> ocular toxicity</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">FOLR1 is a target.</AbstractText>
          <AbstractText Label="RESULTS">Ocular adverse events were observed.</AbstractText>
        </Abstract>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID Version="1">222</PMID>
      <Article>
        <Journal><ISOAbbreviation>J Clin Oncol</ISOAbbreviation>
          <JournalIssue><PubDate><MedlineDate>2019 Jan-Feb</MedlineDate></PubDate></JournalIssue>
        </Journal>
        <ArticleTitle>A plain title</ArticleTitle>
        <Abstract><AbstractText>Single unlabeled section.</AbstractText></Abstract>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <Article><ArticleTitle>No PMID here</ArticleTitle></Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>"""


def test_parse_efetch_xml_structured_abstract_and_markup():
    recs = ps._parse_efetch_xml(_XML, category="safety")
    assert [r.pmid for r in recs] == ["111", "222"]  # PMID-less record skipped
    r0 = recs[0]
    # inline <i> markup contributes its text, not a split/dropped token
    assert r0.title == "Mirvetuximab and FOLR1 ocular toxicity"
    # labeled sections joined IN ORDER with their labels — RESULTS text is retained
    assert r0.abstract == "BACKGROUND: FOLR1 is a target. RESULTS: Ocular adverse events were observed."
    assert r0.journal == "Nature Cancer"
    assert r0.year == 2021
    assert r0.category == "safety"


def test_parse_efetch_xml_medline_date_and_isoabbrev_fallbacks():
    r = ps._parse_efetch_xml(_XML, category="clinical")[1]
    assert r.year == 2019  # MedlineDate "2019 Jan-Feb" → 2019
    assert r.journal == "J Clin Oncol"  # ISOAbbreviation when Title absent
    assert r.abstract == "Single unlabeled section."


def test_xml_text_none_and_whitespace_collapse():
    assert ps._xml_text(None) == ""
    import xml.etree.ElementTree as ET

    el = ET.fromstring("<t>a   b\n  <i>c</i>  d</t>")
    assert ps._xml_text(el) == "a b c d"


def test_eutils_params_adds_identity_when_configured(monkeypatch):
    monkeypatch.setattr(ps, "NCBI_API_KEY", "KEY123")
    monkeypatch.setattr(ps, "NCBI_TOOL", "mytool")
    monkeypatch.setattr(ps, "NCBI_EMAIL", "a@b.co")
    out = ps._eutils_params({"db": "pubmed"})
    assert out == {"db": "pubmed", "api_key": "KEY123", "tool": "mytool", "email": "a@b.co"}


def test_eutils_params_omits_identity_when_unset(monkeypatch):
    monkeypatch.setattr(ps, "NCBI_API_KEY", "")
    monkeypatch.setattr(ps, "NCBI_TOOL", "")
    monkeypatch.setattr(ps, "NCBI_EMAIL", "")
    src = {"db": "pubmed"}
    out = ps._eutils_params(src)
    assert out == {"db": "pubmed"}
    assert src == {"db": "pubmed"}  # input dict never mutated


def test_cache_key_strips_identity_params():
    # same logical request, different api_key/tool → identical cache key
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?term=KRAS&retmode=json"
    a = ps._cache_key(base + "&api_key=AAA&tool=t1&email=x@y.z")
    b = ps._cache_key(base + "&api_key=BBB")
    c = ps._cache_key(base)
    assert a == b == c
    # a different query → different key
    assert ps._cache_key(base.replace("KRAS", "BRAF")) != c


def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv(ps._CACHE_DIR_ENV, str(tmp_path))
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?id=111&retmode=xml"
    assert ps._cache_read(url) is None
    ps._cache_write(url, "BODY")
    assert ps._cache_read(url) == "BODY"


def test_cache_disabled_when_env_unset(tmp_path, monkeypatch):
    monkeypatch.delenv(ps._CACHE_DIR_ENV, raising=False)
    ps._cache_write("http://x/y?z=1", "BODY")  # no-op
    assert ps._cache_read("http://x/y?z=1") is None


class _FakeResp:
    def __init__(self, body):
        self._b = body.encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_http_get_backoff_retries_then_succeeds(monkeypatch):
    monkeypatch.delenv(ps._CACHE_DIR_ENV, raising=False)
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)
        return _FakeResp("OK")

    monkeypatch.setattr(ps.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ps.time, "sleep", lambda *_: None)  # no real backoff sleep
    assert ps._http_get("http://x/y", timeout_s=1.0) == "OK"
    assert calls["n"] == 3  # two 503s retried, third succeeded


def test_http_get_does_not_retry_non_transient_404(monkeypatch):
    monkeypatch.delenv(ps._CACHE_DIR_ENV, raising=False)
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 404, "nope", {}, None)

    monkeypatch.setattr(ps.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ps.time, "sleep", lambda *_: None)
    try:
        ps._http_get("http://x/y", timeout_s=1.0, max_retries=3)
        raise AssertionError("expected HTTPError to propagate")
    except urllib.error.HTTPError as e:
        assert e.code == 404
    assert calls["n"] == 1  # 404 is not retried


def test_efetch_falls_back_to_text_parser_on_xml_error(monkeypatch):
    monkeypatch.delenv(ps._CACHE_DIR_ENV, raising=False)
    # XML fetch returns junk (ParseError); text fetch returns a parseable text record.
    text_body = (
        "1. J Test. 2020;1(1):1-2.\n\nA text-parsed title.\n\n"
        "Author A(1).\n\nThis is the abstract body long enough to win.\n\nPMID: 999\n"
    )
    seq = ["<not-xml", text_body]
    monkeypatch.setattr(ps, "_http_get", lambda url, **k: seq.pop(0))
    recs = ps._efetch_abstracts(["999"], category="biological", timeout_s=1.0)
    assert [r.pmid for r in recs] == ["999"]
    assert recs[0].category == "biological"


def test_efetch_empty_pmids_short_circuits(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not fetch for empty pmid list")

    monkeypatch.setattr(ps, "_http_get", boom)
    assert ps._efetch_abstracts([], category="safety", timeout_s=1.0) == []
