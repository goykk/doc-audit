import pytest

from app.pipelines.mineru_runner import build_blocks, normalized_bbox_to_pixels


def test_normalized_bbox_maps_to_rendered_pixels():
    # content_list title bbox [80,11,376,54] on a 200dpi render of a 595x420pt page
    assert normalized_bbox_to_pixels([80, 11, 376, 54], 1653, 1167) == [
        132.24,
        12.84,
        621.53,
        63.02,
    ]


def test_build_blocks_keeps_one_based_page_and_table_path():
    pages = [{"page": 1, "width": 1000, "height": 500}]
    items = [
        {"type": "text", "text": "hello", "bbox": [0, 0, 500, 100], "page_idx": 0},
        {"type": "table", "table_body": "<table/>", "bbox": [0, 0, 1000, 200], "page_idx": 0},
    ]
    blocks = build_blocks(items, pages, ["tables/table_001.html"])
    assert blocks[0]["page"] == 1
    assert blocks[0]["bbox"] == [0.0, 0.0, 500.0, 50.0]
    assert blocks[1]["table_html"] == "tables/table_001.html"


def test_wrong_bbox_length_is_rejected():
    with pytest.raises(ValueError):
        normalized_bbox_to_pixels([0, 0, 1], 100, 100)
