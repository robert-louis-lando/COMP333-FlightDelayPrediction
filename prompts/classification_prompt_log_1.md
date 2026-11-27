# Classification notebook: LLM usage report (GPT-Luna)

## Scope and evidence

This is a retrospective reconstruction from `notebooks/thirdtimesthecharm.ipynb`, not a verbatim chat transcript. The notebook contains no saved LLM prompts or responses, so it cannot establish that an LLM generated any particular code or recommendation. The “asked” items below are plausible summaries of the work represented in each stage; the produced items describe notebook artifacts, not verified LLM output. Code samples are excerpts from the notebook.

## Stage 1 — Import libraries

- **What I asked (reconstructed):** No model-related LLM request can be inferred from this setup cell.
- **What the notebook contains:** Imports for data handling, preprocessing, classification metrics, and PyTorch.
- **Code sample:**
  ```python
  import numpy as np
  import pandas as pd
  import matplotlib.pyplot as plt
  import seaborn as sns
  from sklearn.metrics import f1_score, roc_auc_score
  ```
- **How I validated it:** I reviewed which imported packages were used by the remaining notebook cells; there is no separate validation or saved LLM response.
- **My judgment:** I kept the report limited to imports that support this experiment and did not infer an LLM recommendation from them.

## Stage 2 — Load data

- **What I asked (reconstructed):** No LLM request is recorded. The notebook loads the integrated flight/weather Parquet file.
- **What the notebook contains:** It checks the configured path, tries a parent-directory fallback, reads the Parquet data, and prints its size and source.
- **Code sample:**
  ```python
  if not data_path.exists():
      data_path = Path.cwd().parent / data_path

  if not data_path.exists():
      raise FileNotFoundError(f"Integrated data file not found: {data_path}")

  flights = pd.read_parquet(data_path)
  ```
- **How I validated it:** I used the notebook's displayed load message and preview to confirm the path, 1,929,930-row/34-column shape, and that records were present.
- **My judgment:** I retained the explicit missing-file error and path fallback because they make the data-loading failure visible instead of silently continuing.

## Stage 3 — Prepare data and train a baseline neural network

- **What I asked (reconstructed, not verbatim):** How can I prepare the flight/weather columns for a PyTorch classifier predicting `DepDel15` and establish a baseline?
- **What the notebook contains:** It drops `WeatherDelay` to avoid target leakage, coerces numeric and date values, ordinal-encodes categorical columns, fills missing values with zero, and trains a feed-forward network with a weighted binary loss. These are notebook artifacts; their authorship is unverified.
- **Code sample:**
  ```python
  self.network = nn.Sequential(
      nn.Linear(input_size, 128),
      nn.ReLU(),
      nn.Dropout(0.3),
      nn.Linear(128, 64),
      nn.ReLU(),
      nn.Dropout(0.2),
      nn.Linear(64, 1),
  )

  pos_weight = negative / positive
  criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
  ```
- **How I validated it:** I inspected the saved loss progression and the held-out baseline scores (binary F1 = 0.1967, macro F1 = 0.4986) to confirm the model trained and produced metrics.
- **My judgment:** I used the weighted loss to account for the class imbalance indicated by the positive/negative counts, and kept this run as the comparison point for later preprocessing experiments.

## Stage 4 — Clean and retrain

- **What I asked (reconstructed, not verbatim):** What happens to the classifier if rows with missing values are removed and weather columns with many missing values are excluded?
- **What the notebook contains:** It drops `wind_gust` and `wet_bulb_temperature`, removes incomplete rows, re-encodes features, and retrains the network. The notebook does not preserve an LLM recommendation for these choices.
- **Code sample:**
  ```python
  data_cleaned = data_cleaned.dropna()
  data_cleaned = data_cleaned.drop(
      columns=["wind_gust", "wet_bulb_temperature"]
  )
  data_cleaned[date_columns] = data_cleaned[date_columns].apply(
      lambda col: pd.to_datetime(col, errors="coerce").dt.day_of_year
  )
  ```
- **How I validated it:** I read the resulting F1 values in the saved comparison table and checked them against the baseline: binary F1 rose from 0.1967 to 0.2095, and macro F1 from 0.4986 to 0.5253.
- **My judgment:** I treated complete-case cleaning as one candidate, not an automatic improvement: it improves these saved scores, but dropping records may also change the dataset and deserves further missing-data analysis.

## Stage 5 — Transform features and retrain

- **What I asked (reconstructed, not verbatim):** How could numerical, date, and categorical features be represented more appropriately for the neural network?
- **What the notebook contains:** It standardizes numerical values, expands dates into month/day/day-of-week fields, and one-hot encodes categorical features before training.
- **Code sample:**
  ```python
  preprocessor = ColumnTransformer(
      transformers=[
          ("num", StandardScaler(), numerical_columns),
          ("cat", OneHotEncoder(
              handle_unknown="ignore", sparse_output=False
          ), categorical_columns),
      ],
      remainder="drop",
  )
  ```
- **How I validated it:** I compared the saved binary and macro F1 values with the other runs; this variant recorded 0.2299 binary F1 and 0.5255 macro F1, the highest values in the notebook's comparison tables.
- **My judgment:** I regarded scaling and one-hot encoding as more suitable representations for these feature types than ordinal codes, and selected this run as the current candidate while recognizing the comparison is limited to the recorded experiments.

## Stage 6 — Select features and retrain

- **What I asked (reconstructed, not verbatim):** Which redundant or less useful location/weather metadata columns could be removed while retaining predictive performance?
- **What the notebook contains:** It removes several location, station, and metadata columns, retains airport sequence IDs, flight date components, and selected weather/flight features, then applies scaling and one-hot encoding.
- **Code sample:**
  ```python
  categorical_columns = [
      "OriginAirportSeqID",
      "DestAirportSeqID",
      "FlightDate_month",
      "FlightDate_day",
      "FlightDate_day_of_week",
  ]
  ```
- **How I validated it:** I checked the feature-selected row in the comparison tables: binary F1 = 0.2214 and macro F1 = 0.5091, below the transformed run's 0.2299 and 0.5255.
- **My judgment:** I retained the feature-selection run as a useful comparison, but would not claim that the removed fields were unimportant based on this single experiment; the measured scores favor the transformed feature set.

## Stage 7 — Compare experiments

- **What I asked (reconstructed, not verbatim):** How do the training losses and test F1 scores compare across the raw, cleaned, transformed, and feature-selected datasets?
- **What the notebook contains:** A training-loss plot and tables comparing binary and macro F1 against the raw baseline. The transformed variant has the highest saved F1 values in those tables.
- **Code sample:**
  ```python
  macro_scores = {
      "Data preparation step": [
          "Cleaning", "Transformation", "Feature selection"
      ],
      "Baseline score": [
          f1_macro_raw, f1_macro_raw, f1_macro_raw
      ],
      "New score": [
          f1_macro_cleaned, f1_macro_transformed, f1_macro_extracted
      ],
  }
  ```
- **How I validated it:** I reviewed the rendered score tables and confirmed the reported differences match the saved values: transformation improves macro F1 by 0.0269 over the raw baseline, compared with 0.0268 for cleaning and 0.0105 for feature selection.
- **My judgment:** I used the side-by-side results to favor the transformed run for follow-up, but would rerun the comparison with fixed seeds and confirmed training settings before drawing a firm conclusion.

## Reproducibility note

Some metric print statements in the cleaning, transformation, and feature-selection cells still say “Raw Dataset,” although the variables and comparison tables identify the corresponding experiment. I relied on the stored metric variables and comparison tables above, not those stale labels. The saved training output shows 20 epochs, while the training function declares a default of 200; the notebook does not explain that discrepancy, so the recorded run settings should be confirmed before treating the results as reproducible.