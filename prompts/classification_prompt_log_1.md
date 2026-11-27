# Classification workflow: LLM prompt log (GPT-Sol)

## 1. Data integration

**What I asked the LLM**  
“Help me load and inspect the integrated 2024 flight, airport, and weather dataset so I can use it for a flight-delay classification model. Check that the file exists and show me its dimensions and sample rows.”

**What the LLM recommended or produced**  
I recommend loading the integrated Parquet dataset directly, checking that the file exists before reading it, and printing its path and dimensions before inspecting a few records. Since this file is already integrated, use it as the modeling input rather than repeating the source joins. The sample load contains **1,929,930 rows and 34 columns**.

Example implementation:

```python
data_path = Path("data/staging/08_integrated/flights_airports_weather_2024.parquet")

if not data_path.exists():
    data_path = Path.cwd().parent / data_path

if not data_path.exists():
    raise FileNotFoundError(f"Integrated data file not found: {data_path}")

flights = pd.read_parquet(data_path)

print(f"Loaded {len(flights):,} rows and {len(flights.columns):,} columns")
print(f"Data source: {data_path}")
pd.set_option('display.max_columns', None)
flights.head()
```

**How I validated it**  
I checked that the file loaded, confirmed the printed dimensions and path, and inspected the preview. It contains flight information such as date, departure time, origin, destination, and `DepDel15`, together with airport and weather fields.

**What changed based on my own judgment**  
I used the existing integrated Parquet file rather than rebuilding the integration process in this notebook. I kept integration upstream and focused this notebook on preparing the combined data for classification.

## 2. Data preparation: cleaning, transformation, and feature selection

**What I asked the LLM**  
“Prepare this mixed flight and weather dataset for a neural network. Exclude columns that would leak the target, convert numeric and date values, encode categoricals, handle missing data, then try scaling, date feature extraction, and feature selection.”

**What the LLM recommended or produced**  
I recommend comparing a few preparation strategies rather than committing to one encoding immediately:

- **Initial/raw version:** copy the input and exclude `WeatherDelay` to avoid target leakage. Coerce numeric fields with `pd.to_numeric(errors="coerce")`, convert `FlightDate`, `DATE`, and `WeatherObservationLocalDateTime` to day-of-year values, ordinal-encode categorical fields, and fill missing values with zero.
- **Cleaned version:** remove incomplete rows and drop `wind_gust` and `wet_bulb_temperature`, then coerce selected columns and remove rows that remain incomplete.
- **Transformed version:** standardize numeric predictors with `StandardScaler`, derive month/day/day-of-week features from dates, and one-hot encode categorical fields with `handle_unknown="ignore"`.
- **Feature-selected version:** remove city/state labels, redundant airport descriptions and coordinates, station identifiers/coordinates, and weather-observation time fields. Retain the flight date and departure time, origin/destination airport sequence IDs, and a smaller set of weather measurements.

Here is code for the initial and cleaned approaches:

```python
data_raw = flights.copy()
data_raw = data_raw.drop(columns='WeatherDelay')

data_raw[numerical_columns] = data_raw[numerical_columns].apply(
    pd.to_numeric, errors='coerce'
)
data_raw[date_columns] = data_raw[date_columns].apply(
    lambda col: pd.to_datetime(col, errors='coerce').dt.day_of_year
)
data_raw[categorical_columns] = ordinal_encoder.fit_transform(
    data_raw[categorical_columns]
)
data_raw = data_raw.fillna(0)
```

```python
flights = flights.drop(columns='WeatherDelay')
data_cleaned = flights.copy()
data_cleaned = data_cleaned.dropna()
data_cleaned = data_cleaned.drop(
    columns=['wind_gust', 'wet_bulb_temperature']
)
```

For the transformed approach, derive calendar fields and apply scaling and one-hot encoding:

```python
def encode_datetime(df, date_columns):
    df = df.copy()

    for col in date_columns:
        df[col] = pd.to_datetime(df[col], errors='coerce')
        df[f'{col}_month'] = df[col].dt.month
        df[f'{col}_day'] = df[col].dt.day
        df[f'{col}_day_of_week'] = df[col].dt.day_of_week

    df = df.drop(columns=date_columns)
    return df

preprocessor = ColumnTransformer(
    transformers=[
        ('num', StandardScaler(), numerical_columns),
        ('cat', OneHotEncoder(handle_unknown='ignore', sparse_output=False),
         categorical_columns)
    ],
    remainder='drop'
)

X_train = preprocessor.fit_transform(X_train)
X_test = preprocessor.transform(X_test)
```

For feature selection, define `columns_to_remove` from the descriptive, location, station, and observation-time fields, then apply:

```python
data_extracted = flights.copy()
data_extracted = data_extracted.drop(columns=columns_to_remove)
```

**How I validated it**  
I inspected each version's dimensions, data types and samples rows.

**What changed based on my own judgment**  
I treated preparation as an experiment rather than settling on the first encoding. I removed `WeatherDelay` because it would leak information related to the delay outcome, tried dropping incomplete records and two weather columns, then tested scaling and richer date encoding. I also manually removed fields I considered redundant or unhelpful. The feature-selected variant scored lower than the transformed variant, so the results did not support that final reduction as an improvement.

## 3. Modeling

**What I asked the LLM**  
“Build a PyTorch binary classifier for `DepDel15` using these prepared features. Account for class imbalance, train it in batches, and let me compare performance across the preparation variants.”

**What the LLM recommended or produced**  
I recommend a feed-forward PyTorch binary classifier with two hidden layers (128 and 64 units), ReLU activations, dropout rates of 0.3 and 0.2, and one output logit. Use `BCEWithLogitsLoss` with a positive-class weight calculated from the training labels to account for class imbalance, Adam with a learning rate of `0.001`, and batches of 1,024. Track and print training loss by epoch, and reuse the same architecture across the raw, cleaned, transformed, and feature-selected data so the variants can be compared.

The model and weighted loss can be implemented as follows:

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
            nn.Linear(64, 1)
        )

    def forward(self, x):
        return self.network(x)

model_raw = NeuralNetwork(X_train.shape[1])

positive = y_train.sum()
negative = len(y_train) - positive
pos_weight = negative / positive

criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
optimizer = torch.optim.Adam(model_raw.parameters(), lr=0.001)
```

Train by iterating over batches, computing the loss, and updating the weights:

```python
for X_batch, y_batch in train_loader:
    predictions = model(X_batch)
    loss = criterion(predictions, y_batch)

    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
```

**How I validated it**  
I reviewed the saved training-loss output: loss generally decreases over the 20 displayed epochs for each variant. I also evaluated each model on its held-out data using binary and macro F1 rather than treating training loss as the final measure of model quality.

**What changed based on my own judgment**  
I kept the general network and training approach consistent while comparing data-preparation variants, so their results could be compared on similar terms. I used a weighted loss for the imbalanced target and tracked both binary and macro F1. The notebook does not preserve the chat history, so it cannot establish which individual design choices were first suggested by the LLM.

## 4. Testing

**What I asked the LLM**  
“Split the data reproducibly while preserving the class balance, evaluate predictions on held-out data, report useful F1 metrics, and compare the results from each preparation approach.”

**What the LLM recommended or produced**  
Use `train_test_split` with a 20% test split, `random_state=42`, and `stratify=y` to preserve the class distribution and make the evaluation reproducible. Fit preprocessing on the training data, then transform the test data without refitting. During evaluation, switch the model to evaluation mode, disable gradient tracking, apply sigmoid to the logits, and classify probabilities at a **0.5** threshold. Report binary and macro F1, and compare each preparation approach with the raw baseline.

Create the split before fitting the preprocessing pipeline:

```python
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)
```

Compute predictions and both F1 measures on the held-out set:

```python
model.eval()
y_true = []
y_pred = []

with torch.no_grad():
    for X_batch, y_batch in test_loader:
        logits = model(X_batch)
        probabilities = torch.sigmoid(logits)
        predictions = (probabilities >= 0.5).int()
        y_true.extend(y_batch.cpu().numpy())
        y_pred.extend(predictions.cpu().numpy())

f1_binary = f1_score(y_true, y_pred, average="binary")
f1_macro = f1_score(y_true, y_pred, average="macro")
```

**How I validated it**  
I compared the saved test results. The transformed version had the highest binary F1 (**0.2299**, versus **0.1967** raw); its macro F1 was **0.5255**, close to the cleaned version’s **0.5253**. Feature selection reduced the results to **0.2214** binary and **0.5091** macro F1. These comparisons support choosing the transformed variant among the runs shown, but do not establish performance on other data.

**What changed based on my own judgment**  
I used stratification and a fixed random seed to make the comparisons reproducible, and I considered both F1 measures when interpreting performance. I did not treat the feature-selected version as better just because it had fewer columns; its saved F1 scores were lower than those of the transformed version. The notebook’s test is limited to the shown holdout split and fixed threshold; it does not show cross-validation or a second untouched final test set.
