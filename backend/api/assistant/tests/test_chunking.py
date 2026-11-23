from api.assistant.chunking import MAX_TOKENS, chunk_pages, clean_pages, embedding_input, estimate_tokens

HEADER = ["SECTION B: SPORTING REGULATIONS", "B7", "2026 Formula 1 Regulations - Section B", "Issue 09"]


def para(num, words=60, word="alpha"):
    return f"{num} " + " ".join([word] * words) + "."


def regs_pages():
    body5 = ["ARTICLE B5: THE COMPETITION", "B5.10 Formation Lap(s) Behind Safety Car"]
    body5 += [para(f"B5.10.{i}", 70) for i in range(1, 9)]
    body6 = ["ARTICLE B6: TYRES", "B6.3 Wet weather tyres", para("B6.3.1", 40), para("B6.3.2", 40)]
    toc = ["ARTICLE B5: THE COMPETITION 41"] + [f"B5.{i} Heading {i} 4{i}" for i in range(1, 10)]
    return [(1, "\n".join(HEADER + ["cover"])), (2, "\n".join(HEADER + toc)),
            (3, "\n".join(HEADER + body5[:6])), (4, "\n".join(HEADER + body5[6:] + body6)),
            (5, "\n".join(HEADER + ["B6.3.3 last paragraph of tyres."]))]


def test_headers_and_toc_removed():
    cleaned = clean_pages(regs_pages())
    assert 2 not in [n for n, _ in cleaned]  # contents page dropped
    text = "\n".join(line for _, ls in cleaned for line in ls)
    assert "Issue 09" not in text and "SECTION B: SPORTING REGULATIONS" not in text


def test_article_numbers_kept_and_never_mixed():
    chunks = chunk_pages(regs_pages())
    assert any(c.article.startswith("B5") for c in chunks)
    for c in chunks:
        tops = {w.split(".")[0] for w in c.text.split() if w[:1] == "B" and w[1:2].isdigit() and "." in w}
        assert len(tops) <= 1, f"chunk mixes articles {tops}"  # B5 and B6 never share a chunk
    b6 = [c for c in chunks if c.article.startswith("B6")]
    assert b6 and b6[0].section.startswith(("B6.3", "ARTICLE B6"))


def test_chunk_sizes_in_range():
    chunks = chunk_pages(regs_pages())
    assert all(c.tokens <= MAX_TOKENS for c in chunks)
    big = [c for c in chunks if c.article.startswith("B5")]
    assert len(big) >= 2 and big[0].tokens >= 300  # B5 is long: packed up to the window, not one line each


def test_page_is_start_page_and_continuation_joined():
    chunks = chunk_pages(regs_pages())
    first_b5 = next(c for c in chunks if c.article.startswith("B5"))
    assert first_b5.page == 3
    last = [c for c in chunks if c.article.startswith("B6")][-1]
    assert "last paragraph of tyres" in last.text and last.page in (4, 5)


def test_unnumbered_decision_is_one_chunk():
    page = "\n".join(["Document 61", "Fact Car 11 made contact with Car 51", "Decision Drop of 5 grid positions"] * 4)
    chunks = chunk_pages([(1, page)])
    assert len(chunks) == 1 and chunks[0].article == "" and chunks[0].page == 1


def test_overlong_paragraph_is_split():
    chunks = chunk_pages([(1, para("33.4", 2000))])
    assert len(chunks) >= 4 and all(c.tokens <= MAX_TOKENS for c in chunks)
    assert chunks[0].article == "33.4"  # older numbering without a letter prefix


def test_embedding_input_adds_section_context():
    c = chunk_pages([(1, "ARTICLE B9: PERSONNEL\nB9.1 General Provisions\nB9.1.1 Text of the rule.")])[0]
    assert embedding_input(c).startswith(("B9.1 General Provisions", "ARTICLE B9"))
    assert estimate_tokens("one two three") >= 3


def test_wrapped_cross_reference_is_not_a_heading():
    text = "B3.5.1 The rule continues and refers to\nArticle B3.5 until the end of the session.\nB3.5.2 Next rule."
    chunks = chunk_pages([(1, text)])
    assert len(chunks) == 1 and chunks[0].article == "B3.5.1"
    assert "Article B3.5 until the end" in chunks[0].text
