# Classification notebook: LLM usage report (GPT-Sol)

## Scope and evidence

This is a retrospective reconstruction from `notebooks/thirdtimesthecharm.ipynb`, not a verbatim chat transcript. The notebook contains no saved LLM prompts or responses, so it cannot establish that an LLM generated any particular code or recommendation. The “asked” items below are plausible summaries of the work represented in each stage; the produced items describe notebook artifacts, not verified LLM output. Code samples are excerpts from the notebook.

## Stage 1 — Import libraries

- **What I asked (reconstructed):** No model-related LLM request can be inferred from this setup cell.
- **What the notebook contains:** Imports for data handling, preprocessing, classification metrics, and PyTorch.
- **Code sample:**
  ```python
  from sklearn.model_selection import train_test_split
  from sklearn.preprocessing import OneHotEncoder, StandardScaler, OrdinalEncoder
  from sklearn.compose import ColumnTransformer
  import torch
  from torch import nn
  ```
- **How I validated it:** I checked the imports against their use in later cells; no separate validation or LLM response is recorded.
- **My judgment:** No modeling decision can be attributed to an LLM from this evidence.

## Stage 2 — Load data

- **What I asked (reconstructed):** No LLM request is recorded. The notebook loads the integrated flight/weather Parquet file.
- **What the notebook contains:** It reads the integrated dataset and reports its size and source path.
- **Code sample:**
  ```python
  data_path = Path("data/staging/08_integrated/flights_airports_weather_2024.parquet")
  flights = pd.read_parquet(data_path)
  ```
- **How I validated it:** I inspected the reported path, shape (1,929,930 rows and 34 columns), and displayed sample records.
- **My judgment:** The notebook uses the integrated 2024 flight/weather dataset; there is no evidence here of an LLM selecting it.

## Stage 3 — Prepare data and train a baseline neural network

- **What I asked (reconstructed, not verbatim):** How can I prepare the flight/weather columns for a PyTorch classifier predicting `DepDel15` and establish a baseline?
- **What the notebook contains:** It drops `WeatherDelay` to avoid target leakage, coerces numeric and date values, ordinal-encodes categorical columns, fills missing values with zero, and trains a feed-forward network with a weighted binary loss. These are notebook artifacts; their authorship is unverified.
- **Code sample:**
  ```python
  data_raw = flights.drop(columns="WeatherDelay")
  data_raw[numerical_columns] = data_raw[numerical_columns].apply(
      pd.to_numeric, errors="coerce"
  )
  data_raw[categorical_columns] = OrdinalEncoder().fit_transform(
      data_raw[categorical_columns]
  )
  data_raw = data_raw.fillna(0)
  ```
- **How I validated it:** I checked the saved baseline test metrics: binary F1 = 0.1967 and macro F1 = 0.4986, and reviewed the target and feature preparation cells.
- **My judgment:** Excluding `WeatherDelay` avoids using information that would leak the outcome. Zero-filling and ordinal encoding were used as a simple first pass, not established as final choices.

## Stage 4 — Clean and retrain

- **What I asked (reconstructed, not verbatim):** What happens to the classifier if rows with missing values are removed and weather columns with many missing values are excluded?
- **What the notebook contains:** It drops `wind_gust` and `wet_bulb_temperature`, removes incomplete rows, re-encodes features, and retrains the network. The notebook does not preserve an LLM recommendation for these choices.
- **Code sample:**
  ```python
  data_cleaned = flights.drop(columns="WeatherDelay").copy()
  data_cleaned = data_cleaned.dropna()
  data_cleaned = data_cleaned.drop(
      columns=["wind_gust", "wet_bulb_temperature"]
  )
  ```
- **How I validated it:** I compared saved test scores with the baseline: binary F1 = 0.2095 and macro F1 = 0.5253, versus 0.1967 and 0.4986. The comparison tables show gains of 0.0127 and 0.0268.
- **My judgment:** I kept this as a separate experiment to compare cleaning with the baseline. I accepted dropping incomplete rows for this iteration; the notebook does not document a missingness analysis proving that is universally best.

## Stage 5 — Transform features and retrain

- **What I asked (reconstructed, not verbatim):** How could numerical, date, and categorical features be represented more appropriately for the neural network?
- **What the notebook contains:** It standardizes numerical values, expands dates into month/day/day-of-week fields, and one-hot encodes categorical features before training.
- **Code sample:**

  ```python
  df[f"{col}_month"] = df[col].dt.month
  df[f"{col}_day"] = df[col].dt.day
  df[f"{col}_day_of_week"] = df[col].dt.day_of_week

  preprocessor = ColumnTransformer(transformers=[
      ("num", StandardScaler(), numerical_columns),
      ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False),
       categorical_columns),
  ])
  ```

- **How I validated it:** I compared saved scores with the baseline: binary F1 = 0.2299 and macro F1 = 0.5255. The comparison table gives baseline deltas of +0.0332 and +0.0269.
- **My judgment:** I preferred this representation for the next experiment because it had the strongest binary F1 among the recorded variants. That choice is based on these saved metrics, not proof of generalization or statistical significance.

## Stage 6 — Select features and retrain

- **What I asked (reconstructed, not verbatim):** Which redundant or less useful location/weather metadata columns could be removed while retaining predictive performance?
- **What the notebook contains:** It removes several location, station, and metadata columns, retains airport sequence IDs, flight date components, and selected weather/flight features, then applies scaling and one-hot encoding.
- **Code sample:**
  ```python
  columns_to_remove = [
      "OriginCityName", "OriginStateName", "DestCityName", "DestStateName",
      "AirportCountryName", "AirportStateName", "AirportCityName",
      "AirportLatitude", "AirportLongitude", "AirportUTCOffset",
      "WeatherStationID", "AirportWeatherStationDistanceKm",
      "WeatherStationPriority", "WeatherStationLatitude",
      "WeatherStationLongitude", "STATION", "DATE",
      "WeatherObservationLocalDateTime", "AirportName",
  ]
  data_extracted = flights.drop(columns=columns_to_remove)
  ```
- **How I validated it:** I compared saved scores with the baseline: binary F1 = 0.2214 and macro F1 = 0.5091; the comparison table reports deltas of +0.0247 and +0.0105. This is below the transformed-feature variant on both measures.
- **My judgment:** I treated feature selection as an experiment rather than assuming removed columns were irrelevant. The saved scores do not justify preferring it over the transformed variant.

## Stage 7 — Compare experiments

- **What I asked (reconstructed, not verbatim):** How do the training losses and test F1 scores compare across the raw, cleaned, transformed, and feature-selected datasets?
- **What the notebook contains:** A training-loss plot and tables comparing binary and macro F1 against the raw baseline. The transformed variant has the highest saved F1 values in those tables.
- **Code sample:**
  ```python
  binary_scores = {
      "Data preparation step": ["Cleaning", "Transformation", "Feature selection"],
      "Baseline score": [f1_binary_raw, f1_binary_raw, f1_binary_raw],
      "New score": [f1_binary_cleaned, f1_binary_transformed, f1_binary_extracted],
  }
  ```
- **How I validated it:** I read the displayed comparison tables and checked their values against the metric outputs saved earlier in the notebook.
- **My judgment:** I would carry the transformed-feature approach forward as the best-performing recorded experiment, while treating the result as provisional and validating it again with reproducible runs and appropriate held-out evaluation.

## Reproducibility note

Some metric print statements in the cleaning, transformation, and feature-selection cells still say “Raw Dataset,” although the variables and comparison tables identify the corresponding experiment. I relied on the stored metric variables and comparison tables above, not those stale labels. The saved training output shows 20 epochs, while the training function declares a default of 200; the notebook does not explain that discrepancy, so the recorded run settings should be confirmed before treating the results as reproducible.
