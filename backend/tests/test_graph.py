"""Tests for the pure helpers in app.graph.

merge_retrieve_results has no I/O and reads no settings (unlike GraphService
itself, which needs a real or fake Neo4j/model setup), so these are plain unit
tests — no fixture, no environment setup, same style as test_chunking.py.
"""

from app.graph import RetrieveResult, merge_retrieve_results


def test_merge_of_empty_list_returns_empty_result() -> None:
    merged = merge_retrieve_results([])

    assert merged == RetrieveResult()


def test_merge_of_one_result_passes_it_through_unchanged() -> None:
    result = RetrieveResult(
        node_ids=["n1", "n2"],
        edge_ids=["e1"],
        facts=["fact one"],
        episode_uuids_by_edge={"e1": ["ep1"]},
        node_names={"n1": "Node One", "n2": "Node Two"},
    )

    merged = merge_retrieve_results([result])

    assert merged == result


def test_merge_dedupes_overlapping_nodes_and_edges_in_first_seen_order() -> None:
    first = RetrieveResult(
        node_ids=["n1"],
        edge_ids=["e1"],
        facts=["fact one"],
        episode_uuids_by_edge={"e1": ["ep1"]},
        node_names={"n1": "Node One"},
    )
    second = RetrieveResult(
        node_ids=["n2", "n1"],
        edge_ids=["e2", "e1"],
        facts=["fact two", "fact one (again)"],
        episode_uuids_by_edge={"e1": ["ep2"], "e2": ["ep3"]},
        node_names={"n2": "Node Two", "n1": "Node One (duplicate wording)"},
    )

    merged = merge_retrieve_results([first, second])

    # n1/e1 came from `first` first, so that's the order they keep; n2/e2 are new.
    assert merged.node_ids == ["n1", "n2"]
    assert merged.edge_ids == ["e1", "e2"]
    # facts stays parallel to the deduped edge_ids: e1's fact is first's version,
    # not second's "fact one (again)" duplicate text.
    assert merged.facts == ["fact one", "fact two"]
    # e1's episode UUIDs are unioned across both results, not just the first's.
    assert merged.episode_uuids_by_edge == {"e1": ["ep1", "ep2"], "e2": ["ep3"]}
    # n1's name is whichever result named it first.
    assert merged.node_names == {"n1": "Node One", "n2": "Node Two"}


def test_merge_does_not_duplicate_an_episode_uuid_seen_in_more_than_one_result() -> None:
    first = RetrieveResult(edge_ids=["e1"], facts=["fact"], episode_uuids_by_edge={"e1": ["ep1"]})
    second = RetrieveResult(
        edge_ids=["e1"], facts=["fact"], episode_uuids_by_edge={"e1": ["ep1", "ep2"]}
    )

    merged = merge_retrieve_results([first, second])

    assert merged.episode_uuids_by_edge == {"e1": ["ep1", "ep2"]}
