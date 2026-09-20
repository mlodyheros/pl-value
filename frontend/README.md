# frontend

Not built yet.

`backend/` holds the data pipeline and the model: it builds the dataset, trains
the value model, and answers predictions through `backend/predict.py`. Work is
staying there until the data and the predictions are right.

When this is built it should talk to the backend through a thin API layer rather
than importing the pipeline directly, so the two stay separable.
