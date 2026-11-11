import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.document_service import _extract_opendocument, _extract_xml_from_zip


def _zip_stream(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    stream.seek(0)
    return stream


def test_extract_opendocument_content_xml_text():
    stream = _zip_stream({
        "content.xml": "<root><p>Hello</p><p>World</p></root>",
    })
    text = _extract_opendocument(stream)
    assert "Hello" in text
    assert "World" in text


def test_extract_xml_from_zip_matches_pattern():
    stream = _zip_stream({
        "ppt/slides/slide1.xml": "<root><a>Slide One</a></root>",
        "ppt/slides/slide2.xml": "<root><a>Slide Two</a></root>",
    })
    text = _extract_xml_from_zip(stream, r"ppt/slides/slide\d+\.xml")
    assert "Slide One" in text
    assert "Slide Two" in text
