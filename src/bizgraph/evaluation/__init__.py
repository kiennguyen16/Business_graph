"""Evaluation of matcher output against blind hand labels.

* `sampler`: stratified, seeded sample of links and abstentions for one matcher version, written as a
  blind file (evidence only) plus a separate decisions file.
* `metrics`: precision / recall with Wilson intervals from a labels file joined to any matcher version.
* `report`: renders `outputs/evaluation.md`.

Labels are keyed by (source, record_id): the true target of a record does not depend on the matcher
version, so one labelled sample can score v2, v3 and later versions.
"""

from bizgraph.evaluation.metrics import wilson_interval

__all__ = ["wilson_interval"]
