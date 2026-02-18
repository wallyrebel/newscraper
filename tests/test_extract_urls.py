from bs4 import BeautifulSoup

from darkhorse_topstory_to_rss import extract_post_urls_from_listing


def test_extract_post_urls_from_listing_filters_and_deduplicates() -> None:
    html = """
    <html>
      <body>
        <a href="https://darkhorsepressnow.com/category/news/top-story/">Category</a>
        <a href="/2026/01/example-story/">Post A</a>
        <a href="/2026/01/example-story/">Post A duplicate</a>
        <a href="https://darkhorsepressnow.com/2025/12/another-story/">Post B</a>
        <a href="/page/2/">Pagination</a>
        <a href="https://example.com/not-darkhorse">External</a>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")

    urls = extract_post_urls_from_listing(soup)

    assert urls == [
        "https://darkhorsepressnow.com/2026/01/example-story",
        "https://darkhorsepressnow.com/2025/12/another-story",
    ]
