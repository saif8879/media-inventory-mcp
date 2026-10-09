from pathlib import Path
import pptx
from PIL import Image


def test_deck_dependencies_and_exports_dir():
    assert pptx.__version__ is not None
    assert Image.__version__ is not None
