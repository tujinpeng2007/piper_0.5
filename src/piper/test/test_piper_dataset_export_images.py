"""Tests for offline image-export helpers."""

from pathlib import Path

import pytest

from piper.piper_dataset_export_images import (
    CATEGORIES,
    build_coco_template,
    choose_indices,
)


def test_choose_indices_samples_at_fixed_interval():
    assert choose_indices(12, every=5) == (0, 5, 10)


def test_choose_indices_honors_limit():
    assert choose_indices(20, every=3, limit=3) == (0, 3, 6)


@pytest.mark.parametrize('total,every,limit', [
    (-1, 1, None),
    (1, 0, None),
    (1, 1, 0),
])
def test_choose_indices_rejects_invalid_values(total, every, limit):
    with pytest.raises(ValueError):
        choose_indices(total, every, limit)


def test_coco_template_has_two_project_categories_and_images():
    images = [{'id': 1, 'file_name': 'images/frame_00001.jpg'}]
    template = build_coco_template(
        Path('/data/example'), '/dataset/camera_third_view/color/image_jpeg', images)
    assert template['categories'] == list(CATEGORIES)
    assert template['images'] == images
    assert template['annotations'] == []
    assert template['info']['source_bag'] == '/data/example'
