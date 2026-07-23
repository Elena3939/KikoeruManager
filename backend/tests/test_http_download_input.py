from app.api import routes


def test_http_download_input_pairs_pikpak_password_on_next_line():
    assert routes._http_download_urls_from_payload([
        "https://mypikpak.com/s/share-a",
        "提取码：A1b2",
        "https://example.com/file.zip",
    ]) == [
        "https://mypikpak.com/s/share-a?pwd=A1b2",
        "https://example.com/file.zip",
    ]


def test_http_download_input_pairs_multiline_pikpak_share_text():
    assert routes._http_download_urls_from_payload([
        "https://drive.mypikpak.com/s/share-b\n访问码: 9z8y",
    ]) == ["https://drive.mypikpak.com/s/share-b?pwd=9z8y"]
