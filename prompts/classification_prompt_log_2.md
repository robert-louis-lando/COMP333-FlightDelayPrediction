# Classification workflow: LLM prompt log (GPT-Luna)

## 1. Data integration

**What I asked the LLM**  
“Help me load and inspect the integrated 2024 flight, airport, and weather dataset so I can use it for a flight-delay classification model. Check that the file exists and show me its dimensions and sample rows.”

**What the LLM recommended or produced**  
Start from the integrated Parquet file, verify that it is available in either the current project directory or its parent, then load it and inspect its shape and a few records. This keeps the classification work focused on the prepared dataset instead of duplicating its upstream integration. The loaded data contains **1,929,930 rows and 34 columns**.

One way to perform this check and load is:

```python
relative_path = Path("data/staging/08_integrated/flights_airports_weather_2024.parquet")
candidate_paths = (relative_path, Path.cwd().parent / relative_path)
data_path = next((path for path in candidate_paths if path.is_file()), None)

if data_path is None:
    raise FileNotFoundError(f"Integrated data file not found: {relative_path}")

flights = pd.read_parquet(data_path)
print(f"Loaded shape: {flights.shape}")
print(f"Source: {data_path}")
display(flights.head())
```

**How I validated it**  
I confirmed the path printed by the load step, checked that the table had the expected 1,929,930-by-34 shape, and looked at the first records. The preview showed flight and target fields alongside airport details and weather measurements.

**What changed based on my own judgment**  
I chose to consume the combined dataset as an input rather than redo the source joins here. That kept this analysis centered on classification and avoided adding a second integration implementation.

## 2. Data preparation: cleaning, transformation, and feature selection

**What I asked the LLM**  
“Prepare this mixed flight and weather dataset for a neural network. Exclude columns that would leak the target, convert numeric and date values, encode categoricals, handle missing data, then try scaling, date feature extraction, and feature selection.”

**What the LLM recommended or produced**  
Try several preparation choices and compare them empirically:

- **Initial version:** remove `WeatherDelay` to prevent leakage, coerce numeric columns, encode dates and categories, and fill missing values.
- **Cleaned version:** remove rows with missing values and omit `wind_gust` and `wet_bulb_temperature`.
- **Transformed version:** scale continuous inputs, expand dates into calendar components, and one-hot encode categorical inputs.
- **Reduced version:** remove descriptive airport and station fields while retaining flight timing, airport sequence IDs, and selected weather variables.

The initial numeric/date/category conversions and missing-value handling can be written as:

```python
data_raw = flights.drop(columns=["WeatherDelay"]).copy()
data_raw[numerical_columns] = data_raw[numerical_columns].apply(
    pd.to_numeric, errors="coerce"
)

for column in date_columns:
    parsed_dates = pd.to_datetime(data_raw[column], errors="coerce")
    data_raw[column] = parsed_dates.dt.dayofyear

data_raw[categorical_columns] = ordinal_encoder.fit_transform(
    data_raw[categorical_columns]
)
data_raw = data_raw.fillna(0)
```

For the cleaned version, first exclude the target-leaking column, drop incomplete records, and then remove the two selected weather fields:

```python
data_cleaned = (
    flights.drop(columns=["WeatherDelay"])
    .dropna()
    .drop(columns=["wind_gust", "wet_bulb_temperature"])
    .copy()
)
```

For the transformed approach, extract calendar features and define a preprocessing step:

```python
for column in date_columns:
    parsed = pd.to_datetime(data_transformed[column], errors="coerce")
    data_transformed[f"{column}_month"] = parsed.dt.month
    data_transformed[f"{column}_day"] = parsed.dt.day
    data_transformed[f"{column}_day_of_week"] = parsed.dt.dayofweek

data_transformed = data_transformed.drop(columns=date_columns)

preprocessor = ColumnTransformer(
    transformers=[
        ("numeric", StandardScaler(), numerical_columns),
        ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False),
         categorical_columns),
    ],
    remainder="drop",
)

X_train_prepared = preprocessor.fit_transform(X_train)
X_test_prepared = preprocessor.transform(X_test)
```

For the reduced feature set, drop the descriptive, location, station, and observation-time fields:

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
data_extracted = flights.drop(columns=columns_to_remove).copy()
```

**How I validated it**  
I inspected the processed samples and compared each version using binary and macro F1 on the held-out data:

| Version | Binary F1 | Macro F1 |
|---|---:|---:|
| Raw | 0.1967 | 0.4986 |
| Cleaned | 0.2095 | 0.5253 |
| Transformed | 0.2299 | 0.5255 |
| Feature-selected | 0.2214 | 0.5091 |

The transformed version had the strongest saved binary F1. The feature-selected version did not improve on it.

**What changed based on my own judgment**  
I removed `WeatherDelay` to avoid leaking information about the outcome. I tested different missing-value strategies, removed two weather columns, added scaled numeric and calendar features, and manually reduced descriptive fields. I kept the comparison results in view instead of presuming that fewer features would yield a better model.

## 3. Modeling

**What I asked the LLM**  
“Build a PyTorch binary classifier for `DepDel15` using these prepared features. Account for class imbalance, train it in batches, and let me compare performance across the preparation variants.”

**What the LLM recommended or produced**  
Use a small feed-forward network with two ReLU hidden layers, dropout for regularization, and a single logit for binary classification. Weight the positive class in `BCEWithLogitsLoss`, optimize with Adam, and train in shuffled batches. Keep this model setup fixed while comparing the four feature-preparation variants.

For example, define the network and optimizer like this:

```python
class NeuralNetwork(nn.Module):
    def __init__(self, input_size):
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(input_size, 128),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(64, 1),
        )

    def forward(self, x):
        return self.network(x)

model_raw = NeuralNetwork(X_train.shape[1])
class_ratio = (y_train == 0).sum() / (y_train == 1).sum()
criterion = nn.BCEWithLogitsLoss(pos_weight=class_ratio)
optimizer = torch.optim.Adam(params=model_raw.parameters(), lr=1e-3)
```

Each batch update follows the standard forward, loss, and optimizer steps:

```python
for features, labels in train_loader:
    optimizer.zero_grad()
    batch_loss = criterion(model_raw(features), labels)
    batch_loss.backward()
    optimizer.step()
```

**How I validated it**  
I checked that the recorded training loss generally fell over the 20 displayed epochs. I then compared the models using held-out binary and macro F1, since decreasing training loss alone does not establish useful classification performance.

**What changed based on my own judgment**  
I kept the network and optimizer setup consistent across the experiments so that the input preparation was the main comparison. I retained class weighting for the imbalanced target and judged results with both binary and macro F1.

## 4. Testing

**What I asked the LLM**  
“Split the data reproducibly while preserving the class balance, evaluate predictions on held-out data, report useful F1 metrics, and compare the results from each preparation approach.”

**What the LLM recommended or produced**  
Reserve 20% of the records for testing, stratify by the target, and set a fixed random seed. Fit any preprocessing only on the training split, then apply that fitted transformation to the test split. Evaluate in inference mode, convert logits to probabilities, threshold at 0.5, and report both binary and macro F1 for comparison with the raw-data baseline.

The reproducible stratified split is:

```python
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)
```

Use the held-out loader to create labels and calculate the two F1 metrics:

```python
model.eval()
actual, predicted = [], []

with torch.no_grad():
    for features, labels in test_loader:
        scores = torch.sigmoid(model(features))
        predicted.extend((scores >= 0.5).int().cpu().numpy())
        actual.extend(labels.cpu().numpy())

binary_f1 = f1_score(actual, predicted, average="binary")
macro_f1 = f1_score(actual, predicted, average="macro")
```

**How I validated it**  
I compared the held-out scores across variants. The transformed data had the highest binary F1 (**0.2299**, compared with **0.1967** for raw data) and macro F1 of **0.5255**. The reduced feature set scored **0.2214** binary F1 and **0.5091** macro F1. These values describe this split, not performance on every future sample.

**What changed based on my own judgment**  
I kept the split stratified and reproducible, and considered both F1 scores when comparing models. I did not favor the smaller feature set simply for being simpler because its scores were lower than the transformed model's. I treated this as an initial evaluation; the workflow uses one holdout split and a fixed threshold, without cross-validation or a separate final test set.
