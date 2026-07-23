from core.markdown import escape_accidental_markdown_links


def test_escape_accidental_markdown_links_escapes_relative_targets():
    assert (
        escape_accidental_markdown_links("[별표 3](일반직등)을 적용한다.")
        == "\\[별표 3](일반직등)을 적용한다."
    )


def test_escape_accidental_markdown_links_preserves_real_links_and_images():
    assert (
        escape_accidental_markdown_links("[법령](https://example.test)을 본다.")
        == "[법령](https://example.test)을 본다."
    )
    assert (
        escape_accidental_markdown_links("[조문](#제1조)을 본다.")
        == "[조문](#제1조)을 본다."
    )
    assert (
        escape_accidental_markdown_links("![대체텍스트](image.png)")
        == "![대체텍스트](image.png)"
    )


def test_escape_accidental_markdown_links_preserves_already_escaped_text():
    assert (
        escape_accidental_markdown_links("\\[별표 3](일반직등)")
        == "\\[별표 3](일반직등)"
    )
