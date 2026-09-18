"""What is left in cli/app.py once every seam is out: flag resolution,
the argument parser, and main().
"""


def test_references_default_to_none(monkeypatch):
    """docs/decisions/0050: a measured run held style, camera variety and
    the location's fixed props with no references, so paying for them --
    in money and in pinned composition -- is no longer the default."""
    import sys

    from historical_video_ai.cli.app import _build_arg_parser

    monkeypatch.setattr(sys, "argv", ["historical-video-ai"])
    args = _build_arg_parser().parse_args([])
    assert args.references == "none"
