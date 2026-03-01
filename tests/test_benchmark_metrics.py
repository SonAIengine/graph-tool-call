"""Tests for benchmark metrics."""

from __future__ import annotations

import math

import pytest

from benchmarks.metrics import ndcg_at_k, precision_at_k, recall_at_k, workflow_coverage


class TestPrecisionAtK:
    def test_perfect_precision(self):
        assert precision_at_k(["a", "b", "c"], {"a", "b", "c"}, 3) == 1.0

    def test_zero_precision(self):
        assert precision_at_k(["x", "y", "z"], {"a", "b"}, 3) == 0.0

    def test_partial_precision(self):
        assert precision_at_k(["a", "x", "b"], {"a", "b"}, 3) == pytest.approx(2.0 / 3)

    def test_k_larger_than_retrieved(self):
        assert precision_at_k(["a"], {"a", "b"}, 5) == pytest.approx(1.0)

    def test_k_zero(self):
        assert precision_at_k(["a", "b"], {"a"}, 0) == 0.0

    def test_empty_retrieved(self):
        assert precision_at_k([], {"a"}, 5) == 0.0


class TestRecallAtK:
    def test_perfect_recall(self):
        assert recall_at_k(["a", "b"], {"a", "b"}, 5) == 1.0

    def test_zero_recall(self):
        assert recall_at_k(["x", "y"], {"a", "b"}, 5) == 0.0

    def test_partial_recall(self):
        assert recall_at_k(["a", "x"], {"a", "b", "c"}, 5) == pytest.approx(1.0 / 3)

    def test_empty_relevant(self):
        assert recall_at_k(["a"], set(), 5) == 1.0  # convention

    def test_k_zero(self):
        assert recall_at_k(["a"], {"a"}, 0) == 0.0


class TestNdcgAtK:
    def test_perfect_ranking(self):
        """All relevant items ranked first."""
        result = ndcg_at_k(["a", "b", "x"], {"a", "b"}, 3)
        assert result == pytest.approx(1.0, abs=1e-5)

    def test_worst_ranking(self):
        """No relevant items in top-k."""
        result = ndcg_at_k(["x", "y", "z"], {"a", "b"}, 3)
        assert result == 0.0

    def test_partial_ranking(self):
        """One relevant item not at top."""
        result = ndcg_at_k(["x", "a"], {"a"}, 2)
        # DCG = 0 + 1/log2(3) = 0.631
        # IDCG = 1/log2(2) = 1.0
        expected = (1.0 / math.log2(3)) / (1.0 / math.log2(2))
        assert result == pytest.approx(expected, abs=1e-5)

    def test_empty_relevant(self):
        assert ndcg_at_k(["a"], set(), 5) == 0.0

    def test_k_zero(self):
        assert ndcg_at_k(["a"], {"a"}, 0) == 0.0


class TestWorkflowCoverage:
    def test_full_coverage(self):
        assert workflow_coverage(["a", "b", "c"], ["a", "b", "c"]) == 1.0

    def test_no_coverage(self):
        assert workflow_coverage(["x", "y"], ["a", "b"]) == 0.0

    def test_partial_coverage(self):
        assert workflow_coverage(["a", "x"], ["a", "b"]) == 0.5

    def test_empty_workflow(self):
        assert workflow_coverage(["a"], []) == 1.0

    def test_extra_retrieved(self):
        assert workflow_coverage(["a", "b", "c", "d"], ["a", "c"]) == 1.0
