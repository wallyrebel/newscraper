from bs4 import BeautifulSoup

from darkhorse_topstory_to_rss import (
    PostItem,
    build_item_description,
    extract_article_paragraphs,
    extract_post_urls_from_listing,
)


def test_extract_post_urls_from_listing_filters_and_deduplicates() -> None:
    html = """
    <html>
      <body>
        <a href="https://darkhorsepressnow.com/category/news/top-story/">Category</a>
        <a href="/2026/01/example-story/">Post A</a>
        <a href="/2026/01/example-story/">Post A duplicate</a>
        <a href="https://darkhorsepressnow.com/2025/12/another-story/">Post B</a>
        <a href="/2026/02/18/">Date archive</a>
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


def test_extract_article_paragraphs_prefers_post_content_container() -> None:
    html = """
    <html>
      <body>
        <div class="menu"><p>Skip to content</p></div>
        <div class="elementor-widget-theme-post-content">
          <div class="elementor-widget-container">
            <p>First full paragraph from the article body.</p>
            <p>Second full paragraph from the article body.</p>
            <p><img src="https://example.com/image.png" /></p>
            <p>Third full paragraph from the article body.</p>
          </div>
        </div>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")

    assert extract_article_paragraphs(soup) == [
        "First full paragraph from the article body.",
        "Second full paragraph from the article body.",
        "Third full paragraph from the article body.",
    ]


def test_build_item_description_uses_full_content_when_available() -> None:
    item = PostItem(
        title="Example",
        link="https://darkhorsepressnow.com/news/example",
        guid="https://darkhorsepressnow.com/news/example",
        pub_date="Wed, 18 Feb 2026 00:00:00 +0000",
        pub_dt_iso="2026-02-18T00:00:00+00:00",
        author="Reporter",
        summary="Only a summary",
        content_html="<p>Paragraph one.</p><p>Paragraph two.</p>",
        image_url="https://example.com/image.jpg",
    )

    description = build_item_description(item)

    assert "Paragraph one." in description
    assert "Paragraph two." in description
    assert "Only a summary" not in description
