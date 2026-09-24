"""Check the model against a reader's judgement, squad by squad.

Aggregate error hides things a person notices immediately. These labels caught
the age curve: a plain parabola peaks at 21 on this data, so the model asked too
much for teenagers and too little for players in their prime, and no summary
metric said so.

The labels are opinion, not truth - at least one disagrees with Transfermarkt
rather than with the model - so this asserts a floor rather than perfection. It
is here to catch a change that quietly reverses the direction of the errors a
reader already flagged.
"""

from pathlib import Path

import pandas as pd
import pytest

from backend.config import PROCESSED_DATASET_PATH
from backend.features import add_derived_features
from backend.model import out_of_fold_predictions

LABELS = Path(__file__).parent / "fixtures" / "human_labels.csv"
# Two dozen opinions cannot demand perfection; this catches a reversal.
MINIMUM_AGREEMENT = 0.80


def _labelled_predictions() -> pd.DataFrame:
    df = add_derived_features(pd.read_csv(PROCESSED_DATASET_PATH))
    # The same out-of-fold figures the app shows: a model scoring players it
    # trained on flatters itself.
    df["ratio"] = out_of_fold_predictions(df) / df.market_value_eur

    labels = pd.read_csv(LABELS, comment="#")
    merged = labels.merge(df[["name", "ratio"]], on="name", how="left")
    return merged.dropna(subset=["ratio"])


@pytest.fixture(scope="module")
def judged():
    if not PROCESSED_DATASET_PATH.exists():
        pytest.skip("no dataset; run python -m backend.sources.build_dataset")
    return _labelled_predictions()


def test_labels_still_refer_to_players_in_the_dataset(judged):
    """A squad turns over; a label pointing at nobody is quietly dead weight."""
    labels = pd.read_csv(LABELS, comment="#")

    assert len(judged) >= len(labels) - 2, (
        f"only {len(judged)} of {len(labels)} labelled players are still in the "
        "dataset - refresh the fixture"
    )


def test_model_errors_point_the_way_a_reader_says_they_do(judged):
    under = (judged.direction == "under") & (judged.ratio < 1)
    over = (judged.direction == "over") & (judged.ratio > 1)
    agreement = (under | over).mean()

    disagreed = judged[~(under | over)].name.tolist()
    assert agreement >= MINIMUM_AGREEMENT, (
        f"only {agreement:.0%} of flagged players err in the direction reported; "
        f"disagreements: {disagreed}"
    )


def test_the_two_directions_really_do_separate(judged):
    """If "asks too little" and "asks too much" had the same median ratio, the
    labels would be noise and this file would be measuring nothing."""
    under = judged[judged.direction == "under"].ratio.median()
    over = judged[judged.direction == "over"].ratio.median()

    assert under < 1 < over
    assert over - under > 0.3
