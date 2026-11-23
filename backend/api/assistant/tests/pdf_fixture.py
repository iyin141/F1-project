"""Build a tiny real text PDF in memory (no files, no network) for parser tests."""


def make_pdf(pages: list[list[str]]) -> bytes:
    objs: list[bytes] = []

    def add(b: bytes) -> int:
        objs.append(b)
        return len(objs)

    add(b"")  # 1: catalog (filled below)
    add(b"")  # 2: pages (filled below)
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    kids = []
    for lines in pages:
        stream = "BT /F1 10 Tf 12 TL 40 760 Td " + " ".join(
            f"({ln.replace('(', '[').replace(')', ']')}) Tj T*" for ln in lines
        ) + " ET"
        s = stream.encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n" % len(s) + s + b"\nendstream")
        page = add(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 800] /Contents %d 0 R "
            b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (content, font)
        )
        kids.append(page)
    objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % len(kids)
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)
