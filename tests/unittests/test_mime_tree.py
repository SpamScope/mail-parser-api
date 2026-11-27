import json

import pytest

from mail_parser_api.mime_tree import (
    MAX_MIME_TREE_PARTS,
    MAX_MIME_TREE_TEXT,
    MAX_STRUCTURE_TEXT,
    read_mime_tree,
)


def entry(index: int, **values):
    return {
        "index": index,
        "parent": None if index == 0 else 0,
        "depth": 0 if index == 0 else 1,
        "content_type": "text/plain",
        "filename": None,
        "size": 1,
        "roles": ["body"],
        "defects": [],
        "recovered": False,
        "embedded_headers": None,
        **values,
    }


def read(entries, indent=2):
    # The CLI prints the tree after the mail; ``start`` is where the mail ends.
    text = '{"subject": "x"}\n' + json.dumps(entries, indent=indent) + "\n"
    return read_mime_tree(text, text.index("\n"))


def test_whole_tree_is_kept_with_an_empty_cut():
    tree = [entry(0, content_type="multipart/mixed"), entry(1)]

    kept, left_out = read(tree)

    assert kept == [{**part, "cut": []} for part in tree]
    assert left_out == 0


@pytest.mark.parametrize("indent", [None, 0, 2])
def test_any_json_layout_is_read(indent):
    kept, left_out = read([entry(0), entry(1)], indent=indent)

    assert [part["index"] for part in kept] == [0, 1]
    assert left_out == 0


def test_empty_array_is_an_empty_tree():
    assert read([]) == ([], 0)


def test_entries_past_the_limit_are_counted():
    kept, left_out = read([entry(index) for index in range(600)])

    assert len(kept) == MAX_MIME_TREE_PARTS
    assert [part["index"] for part in kept] == list(range(MAX_MIME_TREE_PARTS))
    assert left_out == 100


def test_long_value_is_cut_and_named():
    kept, _ = read([entry(0, filename="a" * 5000)])

    assert kept[0]["filename"] == "a" * MAX_STRUCTURE_TEXT
    assert kept[0]["cut"] == ["filename"]


def test_value_at_the_bound_is_not_cut():
    kept, _ = read([entry(0, filename="a" * MAX_STRUCTURE_TEXT)])

    assert kept[0]["cut"] == []


def test_embedded_headers_are_cut_and_named():
    headers = {"from": "a@example.com", "subject": "s" * 2000, "date": None}

    kept, _ = read([entry(0, embedded_headers=headers)])

    assert kept[0]["embedded_headers"] == {
        "from": "a@example.com",
        "subject": "s" * MAX_STRUCTURE_TEXT,
        "date": None,
    }
    assert kept[0]["cut"] == ["embedded_headers.subject"]


def test_control_characters_are_kept_as_declared():
    name = "invoice‮fdp.exe\x1b[2J"

    kept, _ = read([entry(0, filename=name)])

    assert kept[0]["filename"] == name


def test_text_bound_keeps_a_prefix_and_counts_the_rest():
    # 10 characters of content_type plus 1000 of filename: 1010 per entry.
    tree = [entry(index, filename="f" * 1000) for index in range(300)]
    fitting = MAX_MIME_TREE_TEXT // 1010

    kept, left_out = read([*tree, entry(300)])

    assert len(kept) == fitting
    # A short entry after the first one left out is left out too.
    assert left_out == len(tree) + 1 - fitting


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("", id="nothing"),
        pytest.param("{}", id="object"),
        pytest.param("[1]", id="entry-not-an-object"),
        pytest.param('[{"index": 0}', id="not-closed"),
        pytest.param('[{"index": 0} {"index": 1}]', id="no-comma"),
        pytest.param('[{"index": 0},]', id="trailing-comma"),
    ],
)
def test_malformed_tree_raises(text):
    with pytest.raises(ValueError):  # noqa: PT011 - every malformed shape
        read_mime_tree(text, 0)
