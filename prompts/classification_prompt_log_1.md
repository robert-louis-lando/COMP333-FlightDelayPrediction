# Classification workflow: LLM prompt log (GPT-Sol)

## 1. Data integration

### Importing the workflow dependencies

**What I asked the LLM**  
“Which libraries should I import for loading the data, preparing features, training the PyTorch classifier, and evaluating it?”

**What the LLM recommended or produced**  
Import the data, preprocessing, plotting, metrics, and PyTorch utilities used throughout the notebook.

```python
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import matplotlib.pyplot as plt
import seaborn as sns

sns.set_theme(style="whitegrid")

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder, StandardScaler, OrdinalEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.dummy import DummyClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    roc_auc_score,
)
import torch
from torch import nn
from torch.utils.data import TensorDataset, DataLoader
```

**How I validated it**  
I checked the later notebook cells against these imports: pandas and NumPy support data handling, scikit-learn provides the split/preprocessing/metrics, and PyTorch provides the model and loaders. The plotting imports are used for the loss comparison, while some imported utilities are not used in the shown workflow.

**What changed based on my own judgment**  
I kept the notebook's import cell together at the start so later sections share one setup. I did not remove unused imports because this log is documenting the notebook rather than refactoring its dependencies.

### Loading the integrated dataset

**What I asked the LLM**  
“Show me how to locate and load the integrated 2024 flight, airport, and weather dataset, and make the file lookup fail clearly if the dataset is missing.”

**What the LLM recommended or produced**  
Use the integrated Parquet file directly rather than repeating the upstream joins. Check the expected path and its parent-relative fallback before reading it.

```python
from pathlib import Path

data_path = Path("data/staging/08_integrated/flights_airports_weather_2024.parquet")

if not data_path.exists():
    data_path = Path.cwd().parent / data_path

if not data_path.exists():
    raise FileNotFoundError(f"Integrated data file not found: {data_path}")

flights = pd.read_parquet(data_path)
```

**How I validated it**  
The notebook reports the resolved path and dimensions in the following inspection cell; that output confirms the read completed. The explicit `FileNotFoundError` guard also prevents a missing file from being mistaken for a successful load.

**What changed based on my own judgment**  
I used the existing integrated Parquet file rather than rebuilding the source joins in this notebook. This keeps the notebook focused on classification preparation and avoids duplicating the upstream integration workflow.

### Inspecting the loaded dataset

**What I asked the LLM**  
“After loading the integrated dataset, show its dimensions and a sample of rows so I can confirm it is suitable for classification.”

**What the LLM recommended or produced**  
Print the row and column counts, show the resolved data path, and inspect a preview with all columns visible. The sample load contains **1,929,930 rows and 34 columns**.

```python
print(f"Loaded {len(flights):,} rows and {len(flights.columns):,} columns")
print(f"Data source: {data_path}")
pd.set_option('display.max_columns', None)
flights.head()
```

**How I validated it**  
I confirmed the displayed row and column counts and inspected the preview. It includes the target `DepDel15`, flight date and departure time, origin/destination details, airport attributes, and weather measurements needed to understand what enters preparation.

**What changed based on my own judgment**  
I used this preview as a sanity check rather than adding new integration steps. The remaining work focuses on preparing the existing combined dataset for classification.

## 2. Data preparation: cleaning, transformation, and feature selection

### Excluding the leakage field

**What I asked the LLM**  
“Start a raw baseline by copying the integrated data and removing `WeatherDelay`, which could leak information about the delay target.”

**What the LLM recommended or produced**  
Copy `flights` and drop `WeatherDelay` before preparing the raw baseline.

```python
data_raw = flights.copy()
data_raw = data_raw.drop(columns='WeatherDelay')
```

**How I validated it**  
I confirmed the operation is applied to `data_raw`, leaving the original `flights` object available for the other preparation variants. The subsequent feature selection uses `DepDel15` as the target and no longer carries `WeatherDelay` as an input.

**What changed based on my own judgment**  
I removed only the named leakage field from the raw baseline so its other inputs remain a useful point of comparison. I kept the integrated source data intact for the later cleaned, transformed, and selected-feature experiments.

### Converting and encoding raw features

**What I asked the LLM**  
“Convert the raw baseline's numeric and date columns, encode its categorical fields, and handle missing values.”

**What the LLM recommended or produced**  
Coerce numeric columns, convert dates to day-of-year values, ordinal-encode categoricals, and fill remaining missing values with zero.

```python
numerical_columns = [
    'DepTime', 'DepDel15', 'AirportLatitude', 'AirportLongitude',
    'AirportUTCOffset', 'AirportWeatherStationDistanceKm', 'WeatherStationPriority',
    'WeatherStationLatitude', 'WeatherStationLongitude', 'temperature', 'wind_speed',
    'visibility', 'dew_point_temperature', 'station_level_pressure', 'wind_gust',
    'precipitation', 'wet_bulb_temperature', 'relative_humidity']
data_raw[numerical_columns] = data_raw[numerical_columns].apply(pd.to_numeric, errors='coerce')

date_columns = ['FlightDate', 'DATE', 'WeatherObservationLocalDateTime']
data_raw[date_columns] = data_raw[date_columns].apply(
    lambda col: pd.to_datetime(col, errors='coerce').dt.day_of_year
)

categorical_columns = [
    'OriginAirportSeqID', 'OriginCityName', 'OriginStateName', 'DestAirportSeqID', 'DestCityName',
    'DestStateName', 'AirportCountryName', 'AirportStateName', 'AirportName', 'AirportCityName',
    'WeatherStationID', 'STATION'
    ]
ordinal_encoder = OrdinalEncoder()
data_raw[categorical_columns] = ordinal_encoder.fit_transform(
    data_raw[categorical_columns]
)
data_raw = data_raw.fillna(0)
```

**How I validated it**  
I checked that the numeric conversion, date conversion, and ordinal encoding target the declared column lists. The final `fillna(0)` covers missing values created by failed coercions as well as pre-existing gaps, allowing the raw features to be converted to float32 tensors later.

**What changed based on my own judgment**  
I retained ordinal encoding and zero filling as the raw baseline, not as the preferred general-purpose treatment. The later scaled and one-hot-encoded variant tests a different representation against this simpler setup.

### Splitting and batching the raw data

**What I asked the LLM**  
“Create a reproducible, stratified 80/20 split of the raw baseline and convert the features and target into PyTorch batches.”

**What the LLM recommended or produced**  
Use `random_state=42` and `stratify=y`, convert arrays to float32 tensors, and create shuffled training and non-shuffled test data loaders with batch size 1,024.

```python
target = "DepDel15"
X = data_raw.drop(columns=[target])
y = data_raw[target]
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)
X_train = X_train.to_numpy(dtype=np.float32)
X_test = X_test.to_numpy(dtype=np.float32)

y_train = y_train.to_numpy(dtype=np.float32)
y_test = y_test.to_numpy(dtype=np.float32)

# Convert to tensors
X_train = torch.tensor(X_train, dtype=torch.float32)
X_test = torch.tensor(X_test, dtype=torch.float32)

y_train = torch.tensor(y_train, dtype=torch.float32).reshape(-1, 1)
y_test = torch.tensor(y_test, dtype=torch.float32).reshape(-1, 1)
train_dataset = TensorDataset(X_train, y_train)

train_loader = DataLoader(
    train_dataset,
    batch_size=1024,
    shuffle=True
)
test_dataset = TensorDataset(X_test, y_test)
test_loader = DataLoader(
    test_dataset,
    batch_size=1024,
    shuffle=False
)
X_train_raw = X_train
y_train_raw = y_train
train_loader_raw = train_loader
test_loader_raw = test_loader
```

**How I validated it**  
I checked that the split uses 20% for testing, a fixed seed, and `stratify=y`, then converts both feature and target arrays to float32 tensors. The loaders use the same batch size, with shuffling enabled only for training.

**What changed based on my own judgment**  
I used a reproducible stratified split to preserve the class mix across train and test data. I kept batch size at 1,024 and only shuffled training batches so the later variants follow the same setup.

### Removing incomplete rows and sparse weather columns

**What I asked the LLM**  
“For a cleaned baseline, remove rows without complete observations and drop `wind_gust` and `wet_bulb_temperature`.”

**What the LLM recommended or produced**  
Remove `WeatherDelay`, copy the input, discard incomplete rows, and remove the two selected weather columns.

```python
flights = flights.drop(columns='WeatherDelay')
data_cleaned = flights.copy()
data_cleaned = data_cleaned.dropna()
data_cleaned = data_cleaned.drop(
    columns=['wind_gust', 'wet_bulb_temperature']
)
```

**How I validated it**  
I confirmed the cleaned copy drops missing rows before removing the two selected columns, and that these operations do not alter the raw `data_raw` baseline. The next preparation steps operate on the cleaned object.

**What changed based on my own judgment**  
I treated complete-case cleaning as an experiment because it can remove many records along with their missing values. I did not assume fewer missing values would automatically improve model performance.

### Converting the cleaned features

**What I asked the LLM**  
“Convert the cleaned version's numeric, date, and categorical features, and remove any rows that remain incomplete after conversion.”

**What the LLM recommended or produced**  
Coerce numeric columns, represent dates as day-of-year values, ordinal-encode categoricals, and drop rows that still contain missing values.

```python
numerical_columns = [
    'DepTime', 'DepDel15', 'AirportLatitude', 'AirportLongitude',
    'AirportUTCOffset', 'AirportWeatherStationDistanceKm', 'WeatherStationPriority',
    'WeatherStationLatitude', 'WeatherStationLongitude', 'temperature', 'wind_speed',
    'visibility', 'dew_point_temperature', 'station_level_pressure',
    'precipitation', 'relative_humidity']
date_columns = ['FlightDate', 'DATE', 'WeatherObservationLocalDateTime']
categorical_columns = [
    'OriginAirportSeqID', 'OriginCityName', 'OriginStateName', 'DestAirportSeqID', 'DestCityName',
    'DestStateName', 'AirportCountryName', 'AirportStateName', 'AirportName', 'AirportCityName',
    'WeatherStationID', 'STATION'
    ]
data_cleaned[numerical_columns] = data_cleaned[numerical_columns].apply(pd.to_numeric, errors='coerce')
data_cleaned[date_columns] = data_cleaned[date_columns].apply(
    lambda col: pd.to_datetime(col, errors='coerce').dt.day_of_year
)
data_cleaned[categorical_columns] = ordinal_encoder.fit_transform(data_cleaned[categorical_columns])
data_cleaned = data_cleaned.dropna()
```

**How I validated it**  
I checked that the listed numeric, date, and categorical columns are converted, then that remaining missing rows are dropped. This final removal is important because date parsing and numeric coercion can introduce new missing values.

**What changed based on my own judgment**  
I kept ordinal encoding consistent with the raw baseline so this comparison primarily tests the missing-row policy and removal of the two weather columns. I did not add scaling or one-hot encoding to this version.

### Splitting and batching the cleaned data

**What I asked the LLM**  
“Create a reproducible stratified split of the cleaned version and prepare its tensors and data loaders for training.”

**What the LLM recommended or produced**  
Use the same 80/20 split, fixed seed, class stratification, float32 tensors, and batch size of 1,024 as the raw baseline.

```python
target = "DepDel15"
X = data_cleaned.drop(columns=[target])
y = data_cleaned[target]
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)
X_train = X_train.to_numpy(dtype=np.float32)
X_test = X_test.to_numpy(dtype=np.float32)

y_train = y_train.to_numpy(dtype=np.float32)
y_test = y_test.to_numpy(dtype=np.float32)

# Convert to tensors
X_train = torch.tensor(X_train, dtype=torch.float32)
X_test = torch.tensor(X_test, dtype=torch.float32)

y_train = torch.tensor(y_train, dtype=torch.float32).reshape(-1, 1)
y_test = torch.tensor(y_test, dtype=torch.float32).reshape(-1, 1)
train_dataset = TensorDataset(X_train, y_train)

train_loader = DataLoader(
    train_dataset,
    batch_size=1024,
    shuffle=True
)
test_dataset = TensorDataset(X_test, y_test)
test_loader = DataLoader(
    test_dataset,
    batch_size=1024,
    shuffle=False
)
X_train_cleaned = X_train
y_train_cleaned = y_train
train_loader_cleaned = train_loader
test_loader_cleaned = test_loader
```

**How I validated it**  
I checked that the cleaned variant uses the same 80/20 stratified split, random seed, float32 tensor conversion, and batch size as the raw baseline. The separate aliases preserve its tensors and loaders when the notebook proceeds to the next variant.

**What changed based on my own judgment**  
I kept split and batching settings consistent with the raw baseline so preparation differences, rather than evaluation setup, drive the comparison. I saved the cleaned loader references because the notebook otherwise reuses the generic loader names.

### Cleaning data for the transformed approach

**What I asked the LLM**  
“For the transformed approach, remove the two selected weather fields and create a reusable cleaning step for incomplete and nonnumeric values.”

**What the LLM recommended or produced**  
Drop `wind_gust` and `wet_bulb_temperature`, remove incomplete rows, coerce the selected numeric columns, and remove rows that remain incomplete.

```python
flights = flights.drop(columns=['wind_gust', 'wet_bulb_temperature'])
data_transformed = flights.copy()

def clean(data: pd.DataFrame) -> pd.DataFrame:
    data = data.dropna()
    data[numerical_columns] = data[numerical_columns].apply(pd.to_numeric, errors='coerce')
    data = data.dropna()
    return data

data_transformed = clean(data_transformed)
```

**How I validated it**  
I checked that the helper removes incomplete rows before and after coercing the selected numeric columns. The second `dropna()` handles invalid numeric values that `errors='coerce'` converts to missing data.

**What changed based on my own judgment**  
I kept this as a separate preprocessing path from the earlier complete-case version. It supplies numeric data to the transformed pipeline, which then applies its own date extraction, scaling, and one-hot encoding.

### Extracting calendar features

**What I asked the LLM**  
“Convert the flight and weather dates into month, day, and weekday features for the transformed approach.”

**What the LLM recommended or produced**  
Parse each date with `pd.to_datetime`, add calendar fields, drop the original date columns, and remove the target from the numeric predictor list.

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

data_transformed = encode_datetime(data_transformed, date_columns)
numerical_columns.remove('DepDel15')
```

**How I validated it**  
I checked that the helper parses each requested date, creates month/day/day-of-week fields, and drops the original columns. The target is also removed from `numerical_columns` before that list is passed to the predictor transformer.

**What changed based on my own judgment**  
I chose calendar components to preserve month, day, and weekday distinctions instead of representing each date with only a day-of-year number. The same helper is reused for the reduced feature set later.

### Encoding, scaling, and batching transformed data

**What I asked the LLM**  
“One-hot encode the transformed categorical and calendar features, standardize numeric predictors, and create the training and test loaders.”

**What the LLM recommended or produced**  
Add the derived calendar fields to the categorical feature list, fit a `ColumnTransformer` on the training split, transform the test split without refitting, then create the PyTorch tensors and loaders.

```python

new_date_columns = [
    'FlightDate_month', 'FlightDate_day', 'FlightDate_day_of_week',
    'DATE_month', 'DATE_day', 'DATE_day_of_week',
    'WeatherObservationLocalDateTime_month', 'WeatherObservationLocalDateTime_day',
    'WeatherObservationLocalDateTime_day_of_week']
categorical_columns = categorical_columns + new_date_columns

preprocessor = ColumnTransformer(
    transformers=[
        ('num', StandardScaler(), numerical_columns),
        ('cat', OneHotEncoder(handle_unknown='ignore', sparse_output=False), categorical_columns)
    ],
    remainder='drop'
)
```

**How I validated it**  
I checked that `ColumnTransformer` applies `StandardScaler` to numeric predictors and one-hot encoding to the categorical and derived calendar columns. With `remainder='drop'`, unlisted fields are excluded from the transformed matrix.

**What changed based on my own judgment**  
I used standardization and one-hot encoding as alternatives to the raw baseline's ordinal encoding. I kept unknown-category handling enabled so categories found only in the held-out data do not make transformation fail.

### Splitting and batching the transformed data

**What I asked the LLM**  
“Create a stratified holdout split for the transformed features, apply the fitted preprocessor, and build PyTorch data loaders.”

**What the LLM recommended or produced**  
Split before fitting preprocessing, transform the training and test features, convert the result to tensors, and create loaders with the same batch size as the raw baseline.

```python
target = "DepDel15"
X = data_transformed.drop(columns=[target])
y = data_transformed[target]
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)
X_train = preprocessor.fit_transform(X_train)
X_test = preprocessor.transform(X_test)

X_train = torch.tensor(X_train, dtype=torch.float32)
X_test = torch.tensor(X_test, dtype=torch.float32)

y_train = y_train.to_numpy(dtype=np.float32)
y_test = y_test.to_numpy(dtype=np.float32)

y_train = torch.tensor(y_train, dtype=torch.float32).reshape(-1, 1)
y_test = torch.tensor(y_test, dtype=torch.float32).reshape(-1, 1)
train_dataset = TensorDataset(X_train, y_train)

train_loader = DataLoader(
    train_dataset,
    batch_size=1024,
    shuffle=True
)
test_dataset = TensorDataset(X_test, y_test)
test_loader = DataLoader(
    test_dataset,
    batch_size=1024,
    shuffle=False
)
X_train_transformed = X_train
y_train_transformed = y_train
train_loader_transformed = train_loader
test_loader_transformed = test_loader
```

**How I validated it**  
I confirmed the split occurs before preprocessing is fitted, `fit_transform` is called only on training features, and the test features use `transform`. I also checked that both targets and feature matrices are converted to tensors and that aliases retain this variant's train/test loaders.

**What changed based on my own judgment**  
I kept the same stratified split, seed, and batch size as the raw baseline for an interpretable comparison. I saved transformed-specific aliases so later model and evaluation cells use the correct tensors.

### Removing descriptive and location features

**What I asked the LLM**  
“Create a smaller feature set by removing descriptive, location, station, and observation-time fields while retaining flight identifiers, departure time, and useful weather measurements.”

**What the LLM recommended or produced**  
Drop the listed fields and retain flight date, departure time, origin/destination airport sequence IDs, and the selected weather measurements.

```python
flights.head()

columns_to_remove = [
    'OriginCityName', 'OriginStateName', 'DestCityName', 'DestStateName', 'AirportCountryName',
    'AirportStateName', 'AirportCityName', 'AirportLatitude', 'AirportLongitude', 'AirportUTCOffset',
    'WeatherStationID', 'AirportWeatherStationDistanceKm', 'WeatherStationPriority', 'WeatherStationLatitude',
    'WeatherStationLongitude', 'STATION', 'DATE', 'WeatherObservationLocalDateTime', 'AirportName'
    ]
data_extracted = flights.copy()
data_extracted = data_extracted.drop(columns=columns_to_remove)
data_extracted.head()
```

**How I validated it**  
I checked the explicit `columns_to_remove` list against the fields described as labels, coordinates, station identifiers, or observation-time details. The retained preview helps confirm the route identifiers, date, departure time, and selected measurements remain.

**What changed based on my own judgment**  
I retained airport sequence IDs and flight date as compact route and calendar signals, while removing descriptive fields and coordinates that I judged redundant for this experiment. This is a manual feature-selection hypothesis, not a claim that the dropped columns are universally unhelpful.

### Preparing selected features and calendar values

**What I asked the LLM**  
“Clean the reduced feature set and derive calendar fields from the retained flight date.”

**What the LLM recommended or produced**  
Coerce the selected numerical measurements, remove incomplete rows, and use the shared date helper to replace `FlightDate` with month, day, and weekday values.

```python

numerical_columns = [
    'DepTime', 'temperature', 'wind_speed', 'visibility',
    'dew_point_temperature', 'station_level_pressure',
    'precipitation', 'relative_humidity', 'DepDel15'
    ]
data_extracted = clean(data_extracted)
numerical_columns.remove('DepDel15')
data_extracted = encode_datetime(data_extracted, ['FlightDate'])
data_extracted.head()
```

**How I validated it**  
I checked that the reduced version has the selected numeric columns coerced, incomplete rows removed, and `FlightDate` replaced by the three derived calendar fields. The displayed sample provides a quick check that the resulting columns are present.

**What changed based on my own judgment**  
I excluded the weather observation timestamps along with the other observation-time fields and kept only calendar features derived from the flight date. This keeps the reduced representation focused on scheduled flight timing rather than the weather observation timestamp.

### Encoding and batching the selected features

**What I asked the LLM**  
“Scale the selected numeric features, one-hot encode the retained airport and calendar fields, and create stratified train and test loaders.”

**What the LLM recommended or produced**  
Fit the preprocessor on the training split, transform the held-out split, then convert the arrays to tensors and create data loaders.

```python

categorical_columns = [
    'OriginAirportSeqID', 'DestAirportSeqID', 'FlightDate_month',
    'FlightDate_day', 'FlightDate_day_of_week'
    ]
preprocessor = ColumnTransformer(
    transformers=[
        ('num', StandardScaler(), numerical_columns),
        ('cat', OneHotEncoder(handle_unknown='ignore', sparse_output=False), categorical_columns)
    ],
    remainder='drop'
)
```

**How I validated it**  
I checked that numeric measurements are scaled and that the one-hot encoder receives only the retained airport identifiers and flight-date calendar features. Other columns are omitted by the transformer because the remainder is set to `drop`.

**What changed based on my own judgment**  
I used scaling and one-hot encoding here to keep the reduced-feature experiment comparable with the broader transformed approach. I did not change the retained columns based on the encoding step itself.

### Splitting and batching the selected features

**What I asked the LLM**  
“Fit the selected-feature preprocessor on a stratified training split and create tensors and data loaders for both splits.”

**What the LLM recommended or produced**  
Use the same 80/20 split and fixed seed, fit the scaler and one-hot encoder on the training data, transform the test data, and create batches of 1,024.

```python

target = "DepDel15"
X = data_extracted.drop(columns=[target])
y = data_extracted[target]
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)
X_train = preprocessor.fit_transform(X_train)
X_test = preprocessor.transform(X_test)

X_train = torch.tensor(X_train, dtype=torch.float32)
X_test = torch.tensor(X_test, dtype=torch.float32)

y_train = y_train.to_numpy(dtype=np.float32)
y_test = y_test.to_numpy(dtype=np.float32)

y_train = torch.tensor(y_train, dtype=torch.float32).reshape(-1, 1)
y_test = torch.tensor(y_test, dtype=torch.float32).reshape(-1, 1)
train_dataset = TensorDataset(X_train, y_train)

train_loader = DataLoader(
    train_dataset,
    batch_size=1024,
    shuffle=True
)
test_dataset = TensorDataset(X_test, y_test)
test_loader = DataLoader(
    test_dataset,
    batch_size=1024,
    shuffle=False
)
X_train_extracted = X_train
y_train_extracted = y_train
train_loader_extracted = train_loader
test_loader_extracted = test_loader
```

The notebook reuses `X_train`, `y_train`, `train_loader`, and `test_loader` for each variant. These aliases keep each variant's tensors and loaders available for the model and evaluation examples below.

**How I validated it**  
I checked the stratified split, preprocessing fit/transform calls, tensor conversion, batch settings, and saved aliases for this variant. The later held-out comparison reports lower binary and macro F1 than the transformed version.

**What changed based on my own judgment**  
I kept this as a feature-selection experiment rather than assuming that a smaller input set is better. The lower saved scores led me not to recommend this reduction over the transformed version in the runs shown.

## 3. Modeling

### Defining the classifier

**What I asked the LLM**  
“Define a PyTorch binary classifier for `DepDel15` that can use the prepared feature matrices.”

**What the LLM recommended or produced**  
Use a feed-forward network with two hidden layers (128 and 64 units), ReLU activations, dropout rates of 0.3 and 0.2, and one output logit.

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
```

**How I validated it**  
I checked the input layer uses the prepared feature count and that the final linear layer returns one logit for binary classification. The architecture is shared across variants, while each model is initialized with that variant's input dimension.

**What changed based on my own judgment**  
I reused the same two-hidden-layer architecture and dropout settings for all four preparation variants to keep the modeling approach consistent. I varied the prepared inputs rather than changing the network design at the same time.

### Writing the minibatch training loop

**What I asked the LLM**  
“Write a reusable minibatch training function that updates the model and reports average loss each epoch.”

**What the LLM recommended or produced**  
For every epoch, enable training mode, iterate over the data loader, compute the loss, backpropagate, update the optimizer, and return the model together with the loss history. The notebook's function defaults to 100 epochs.

```python
def train_model(model, train_loader, criterion, optimizer, epochs=100):

    history = []

    for epoch in range(epochs):

        model.train()
        total_loss = 0

        for X_batch, y_batch in train_loader:

            predictions = model(X_batch)
            loss = criterion(predictions, y_batch)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            total_loss += loss.item()

        avg_loss = total_loss / len(train_loader)
        history.append(avg_loss)

        print(f"Epoch [{epoch+1}/{epochs}], Loss: {avg_loss:.4f}")

    return model, history
```

**How I validated it**  
I checked that the loop switches to training mode each epoch, resets gradients, backpropagates each batch loss, updates the optimizer, and stores and prints average epoch loss. The returned history is then used by the later loss-comparison plot.

**What changed based on my own judgment**  
I kept one shared training function instead of maintaining four copies of the same minibatch logic. This reduces the chance that the preparation variants are trained with accidentally different update steps.

### Configuring and fitting each model

**What I asked the LLM**  
“Configure a class-weighted loss and Adam optimizer for each preparation variant, then train each model using its corresponding training loader.”

**What the LLM recommended or produced**  
Calculate `pos_weight` from each variant's training labels, initialize `BCEWithLogitsLoss` and Adam at `0.001`, then call the shared training function for each variant.

```python
model_raw = NeuralNetwork(X_train_raw.shape[1])

positive = y_train_raw.sum()
negative = len(y_train_raw) - positive

pos_weight = negative / positive

criterion = nn.BCEWithLogitsLoss(
    pos_weight=pos_weight
)

optimizer = torch.optim.Adam(
    model_raw.parameters(),
    lr=0.001
)
model_raw, history_raw = train_model(
    model_raw,
    train_loader_raw,
    criterion,
    optimizer
)

model_cleaned = NeuralNetwork(X_train_cleaned.shape[1])
positive = y_train_cleaned.sum()
negative = len(y_train_cleaned) - positive
pos_weight = negative / positive
criterion = nn.BCEWithLogitsLoss(
    pos_weight=pos_weight
)
optimizer = torch.optim.Adam(
    model_cleaned.parameters(),
    lr=0.001
)
model_cleaned, history_cleaned = train_model(
    model_cleaned,
    train_loader_cleaned,
    criterion,
    optimizer
)

model_transformed = NeuralNetwork(X_train_transformed.shape[1])
positive = y_train_transformed.sum()
negative = len(y_train_transformed) - positive
pos_weight = negative / positive
criterion = nn.BCEWithLogitsLoss(
    pos_weight=pos_weight
)
optimizer = torch.optim.Adam(
    model_transformed.parameters(),
    lr=0.001
)
model_transformed, history_transformed = train_model(
    model_transformed,
    train_loader_transformed,
    criterion,
    optimizer
)

model_extracted = NeuralNetwork(X_train_extracted.shape[1])
positive = y_train_extracted.sum()
negative = len(y_train_extracted) - positive
pos_weight = negative / positive
criterion = nn.BCEWithLogitsLoss(
    pos_weight=pos_weight
)
optimizer = torch.optim.Adam(
    model_extracted.parameters(),
    lr=0.001
)
model_extracted, history_extracted = train_model(
    model_extracted,
    train_loader_extracted,
    criterion,
    optimizer
)
```

**How I validated it**  
I checked that each model's input dimension, positive-class weight, and training loader come from the matching preparation variant. The saved histories generally decrease over the displayed epochs; I also checked held-out binary and macro F1 because training loss alone does not measure generalization.

**What changed based on my own judgment**  
I used a weighted loss to account for the imbalanced target and tracked both binary and macro F1 for model assessment. The notebook does not preserve the chat history, so I cannot establish which individual design choices originated with the LLM.

## 4. Testing

### Creating a reproducible holdout split

**What I asked the LLM**  
“Split each preparation variant reproducibly while preserving its class balance, and fit preprocessing without using the held-out data.”

**What the LLM recommended or produced**  
Use `train_test_split` with a 20% test split, `random_state=42`, and `stratify=y`. Fit each preprocessing pipeline on the training data only, then transform the test data using the fitted pipeline. The complete split, tensor conversion, and data-loader code for each variant appears in section 2; the split itself is:

```python
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)
```

**How I validated it**  
I confirmed each variant calls `train_test_split` with `test_size=0.2`, `random_state=42`, and `stratify=y`. In the transformed pipelines, the preprocessor is fitted after splitting and only on `X_train`, then applied to `X_test`.

**What changed based on my own judgment**  
I applied the same holdout strategy to all variants so their test metrics could be compared on the same basis. This produces a reproducible comparison, but does not replace cross-validation or a second untouched final test set.

### Writing the held-out evaluator

**What I asked the LLM**  
“Write an evaluation helper that predicts labels from held-out logits and returns binary and macro F1.”

**What the LLM recommended or produced**  
Switch each model to evaluation mode, disable gradient tracking, apply sigmoid to the output logits, classify at a **0.5** threshold, and compute binary and macro F1.

```python
def evaluate_model(model, test_loader):

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

    return f1_binary, f1_macro
```

**How I validated it**  
I checked that evaluation mode and `torch.no_grad()` are used, logits pass through sigmoid, and the fixed threshold produces binary predictions. The helper returns both binary and macro F1 computed from accumulated held-out labels and predictions.

**What changed based on my own judgment**  
I kept the 0.5 threshold fixed across variants and used one shared evaluator so the metric calculation stays consistent. I interpreted these scores as results at that threshold, not as a threshold-optimized maximum.

### Evaluating each trained variant

**What I asked the LLM**  
“Run the held-out evaluator for the raw, cleaned, transformed, and feature-selected models, and print each pair of F1 results.”

**What the LLM recommended or produced**  
Call the helper with each model and its matching test loader, then print binary and macro F1 to four decimal places.

```python
f1_binary_raw, f1_macro_raw = evaluate_model(model_raw, test_loader_raw)
print(f"Raw Dataset Binary F1 Score: {f1_binary_raw:.4f}")
print(f"Raw Dataset Macro F1 Score: {f1_macro_raw:.4f}")

f1_binary_cleaned, f1_macro_cleaned = evaluate_model(model_cleaned, test_loader_cleaned)
print(f"Cleaned Dataset Binary F1 Score: {f1_binary_cleaned:.4f}")
print(f"Cleaned Dataset Macro F1 Score: {f1_macro_cleaned:.4f}")

f1_binary_transformed, f1_macro_transformed = evaluate_model(model_transformed, test_loader_transformed)
print(f"Transformed Dataset Binary F1 Score: {f1_binary_transformed:.4f}")
print(f"Transformed Dataset Macro F1 Score: {f1_macro_transformed:.4f}")

f1_binary_extracted, f1_macro_extracted = evaluate_model(model_extracted, test_loader_extracted)
print(f"Feature Extracted Dataset Binary F1 Score: {f1_binary_extracted:.4f}")
print(f"Feature Extracted Dataset Macro F1 Score: {f1_macro_extracted:.4f}")
```

**How I validated it**  
I checked that each model is paired with its corresponding test loader and that both F1 values are printed to four decimal places. The saved output provides separate results for raw, cleaned, transformed, and feature-selected data.

**What changed based on my own judgment**  
I considered binary F1 for the positive delay class alongside macro F1, which gives weight to both classes. This avoids choosing a variant based only on one view of performance under class imbalance.

### Plotting training-loss histories

**What I asked the LLM**  
“Plot the training-loss histories for the raw, cleaned, transformed, and feature-selected models.”

**What the LLM recommended or produced**  
Plot each saved history on the same axes with labels and a legend.

```python
plt.plot(history_raw, label='Raw')
plt.plot(history_cleaned, label='Cleaned')
plt.plot(history_transformed, label='Transformed')
plt.plot(history_extracted, label='Feature Extracted')

plt.xlabel('Epoch')
plt.ylabel('Loss')
plt.title('Training Loss Comparison')
plt.legend()
plt.show()
```

**How I validated it**  
I checked that the chart includes one history for each preparation variant and labels the axes and legend. The curves show training behavior over epochs, not performance on held-out data.

**What changed based on my own judgment**  
I treated the loss plot as a training diagnostic only. I relied on the held-out F1 comparison, rather than a lower training loss by itself, when judging the variants.

### Comparing held-out F1 scores

**What I asked the LLM**  
“Compare binary and macro F1 for the cleaned, transformed, and feature-selected approaches against the raw baseline.”

**What the LLM recommended or produced**  
Create separate score tables for binary and macro F1, showing each variant's score and its delta from the raw baseline.

```python
binary_scores = {
    "Data preparation step": [
        "Cleaning",
        "Transformation",
        "Feature selection"
    ],
    "Baseline score": [
        f1_binary_raw,
        f1_binary_raw,
        f1_binary_raw
    ],
    "New score": [
        f1_binary_cleaned,
        f1_binary_transformed,
        f1_binary_extracted
    ]
}

df_binary = pd.DataFrame(binary_scores)

df_binary["Delta (New - Baseline)"] = (
    df_binary["New score"] - df_binary["Baseline score"]
)

display(df_binary.round(4))

macro_scores = {
    "Data preparation step": [
        "Cleaning",
        "Transformation",
        "Feature selection"
    ],
    "Baseline score": [
        f1_macro_raw,
        f1_macro_raw,
        f1_macro_raw
    ],
    "New score": [
        f1_macro_cleaned,
        f1_macro_transformed,
        f1_macro_extracted
    ]
}

df_macro = pd.DataFrame(macro_scores)

df_macro["Delta (New - Baseline)"] = (
    df_macro["New score"] - df_macro["Baseline score"]
)

display(df_macro.round(4))
```

**How I validated it**  
I compared the saved held-out tables: the transformed version had the highest binary F1 (**0.2299**, versus **0.1967** raw) and macro F1 of **0.5255**, close to the cleaned version's **0.5253**. Feature selection scored **0.2214** binary and **0.5091** macro F1. These values support the transformed variant among the runs shown, but do not establish performance on other data.

**What changed based on my own judgment**  
I chose the transformed variant among these runs because its saved held-out scores were strongest overall, and did not treat fewer features as an automatic improvement. I would describe this as a result from one fixed holdout split and threshold, not as evidence of performance on new data; the notebook does not show cross-validation or a second untouched final test set.
