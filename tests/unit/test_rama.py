from pathlib import Path

from scrapper.spiders.rama import RamaSpider


def test_parse_xml_extracts_items():
    xml = """
    <partial-response><update><![CDATA[
      <tr role="row">
        <td>SALA CIVIL ID: 123 PROVIDENCIA: SC123-2026 PROCESO: 11001 FECHA: 01/02/2026 PONENTE: Judge TEMA: Tema relevante</td>
      </tr>
    ]]></update></partial-response>
    """

    items = RamaSpider._parse_xml(xml)

    assert len(items) == 1
    assert items[0]["id"] == "123"
    assert items[0]["title"] == "SC123-2026"
    assert items[0]["content"] == "Tema relevante"


def test_rama_spider_has_parse_xml():
    assert callable(RamaSpider._parse_xml)
    assert RamaSpider._parse_xml.__name__ == "_parse_xml"


def test_rama_spider_search_clicked_before_try_counters():
    source = Path("src/scrapper/spiders/rama.py").read_text()
    total_line = None
    try_line = None
    click_flag_line = None
    click_line = None
    for i, line in enumerate(source.splitlines()):
        stripped = line.strip()
        if stripped == "total_yielded = 0":
            total_line = i
        elif stripped.startswith("try:") and total_line is not None and try_line is None:
            try_line = i
        elif stripped == "_search_clicked = True":
            click_flag_line = i
        elif "searchButton" in stripped and ".click()" in stripped:
            click_line = i

    assert total_line is not None, "total_yielded = 0 not found"
    assert try_line is not None and total_line < try_line, (
        f"total_yielded must be initialized before try (found at line {total_line}, try at line {try_line})"
    )
    assert click_flag_line is not None, "_search_clicked = True not found"
    assert click_line is not None, "click() call not found"
    assert click_flag_line < click_line, (
        f"_search_clicked = True must be set before click() (flag at line {click_flag_line}, click at line {click_line})"
    )
