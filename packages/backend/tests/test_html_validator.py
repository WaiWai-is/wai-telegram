"""Tests for html_validator — quality checks before deployment."""

import pytest

from app.services.agent.html_validator import validate_html


# --- Site validation ---


class TestValidateSite:
    def test_valid_site(self):
        html = """<!DOCTYPE html><html><head><title>Test</title></head>
        <body><h1>Hello World</h1><p>This is a test website with enough content to pass validation checks.</p>
        <section><h2>About</h2><p>More content here for testing purposes and validation.</p></section>
        </body></html>"""
        ok, err = validate_html(html, "site")
        assert ok, err

    def test_too_short(self):
        ok, err = validate_html("<html><body>hi</body></html>", "site")
        assert not ok
        assert "too short" in err

    def test_missing_doctype(self):
        ok, err = validate_html("a" * 300, "site")
        assert not ok
        assert "DOCTYPE" in err or "html" in err

    def test_truncated_no_closing_html(self):
        html = "<!DOCTYPE html><html><head></head><body><h1>Test</h1><p>" + "x" * 300
        ok, err = validate_html(html, "site")
        assert not ok
        assert "truncated" in err.lower()

    def test_truncated_no_closing_body(self):
        html = (
            "<!DOCTYPE html><html><head></head><body><h1>Test</h1><p>"
            + "x" * 300
            + "</html>"
        )
        ok, err = validate_html(html, "site")
        assert not ok
        assert "truncated" in err.lower() or "body" in err.lower()

    def test_css_only_no_content(self):
        html = """<!DOCTYPE html><html><head><style>
        body { background: red; color: white; font-size: 14px; margin: 0; }
        h1 { font-size: 2em; }
        </style></head><body><style>more css here</style></body></html>"""
        ok, err = validate_html(html, "site")
        assert not ok
        assert "text content" in err.lower() or "content" in err.lower()

    def test_no_headings(self):
        html = """<!DOCTYPE html><html><head></head><body>
        <p>Some paragraph text that is long enough to pass content check but has no headings at all in the entire page.</p>
        <p>More text here to make sure we pass the length threshold for content validation.</p>
        </body></html>"""
        ok, err = validate_html(html, "site")
        assert not ok
        assert "heading" in err.lower()

    def test_empty_html(self):
        ok, err = validate_html("", "site")
        assert not ok

    def test_none_like(self):
        ok, err = validate_html("   ", "site")
        assert not ok


# --- Presentation validation ---


class TestValidatePresentation:
    def test_valid_presentation(self):
        html = """<!DOCTYPE html><html><head></head><body>
        <div class="reveal"><div class="slides">
        <section><h1>Title</h1></section>
        <section><h2>Slide 2</h2></section>
        <section><h2>Slide 3</h2></section>
        <section><h2>Slide 4</h2></section>
        </div></div>
        <script src="reveal.js"></script>
        </body></html>"""
        ok, err = validate_html(html, "presentation")
        assert ok, err

    def test_no_reveal(self):
        padding = "x" * 200
        html = f"""<!DOCTYPE html><html><head></head><body>
        <section>Slide 1 {padding}</section><section>Slide 2</section><section>Slide 3</section>
        </body></html>"""
        ok, err = validate_html(html, "presentation")
        assert not ok
        assert "reveal" in err.lower()

    def test_too_few_slides(self):
        padding = "x" * 200
        html = f"""<!DOCTYPE html><html><head></head><body>
        <div class="reveal"><section>Only one {padding}</section></div>
        </body></html>"""
        ok, err = validate_html(html, "presentation")
        assert not ok
        assert "slide" in err.lower()


# --- Table validation ---


class TestValidateTable:
    def test_valid_ag_grid(self):
        html = """<!DOCTYPE html><html><head></head><body>
        <div id="grid" class="ag-theme-alpine"></div>
        <script>
        const rowData = [{name: "A"}, {name: "B"}];
        agGrid.createGrid(document.getElementById('grid'), {rowData});
        </script>
        </body></html>"""
        ok, err = validate_html(html, "table")
        assert ok, err

    def test_valid_html_table(self):
        padding = "x" * 200
        html = f"""<!DOCTYPE html><html><head></head><body>
        <table><tr><td>Cell 1 {padding}</td></tr><tr><td>Cell 2</td></tr></table>
        </body></html>"""
        ok, err = validate_html(html, "table")
        assert ok, err

    def test_no_table_or_grid(self):
        padding = "x" * 200
        html = f"""<!DOCTYPE html><html><head></head><body>
        <div><p>Just some text {padding}</p></div>
        </body></html>"""
        ok, err = validate_html(html, "table")
        assert not ok
        assert "grid" in err.lower() or "table" in err.lower()

    def test_grid_without_data(self):
        padding = "x" * 200
        html = f"""<!DOCTYPE html><html><head></head><body>
        <div class="ag-theme-alpine">{padding}</div>
        <script>const x = 1;</script>
        </body></html>"""
        ok, err = validate_html(html, "table")
        assert not ok
        assert "data" in err.lower()
