import pandas as pd
import re

from compatibility_analyzer.config import MAX_SAMPLE_VALUES

def infer_pattern(series):
    non_null = series.dropna().astype(str)

    if non_null.empty:
        return "unknown"

    sample_text = " ".join(non_null.head(20))

    if re.search(r"@", sample_text):
        return "email_like"

    if re.search(r"https?://|www\.", sample_text):
        return "website_like"

    if re.search(r"\+?\d[\d\s\-\(\)]{6,}", sample_text):
        return "phone_like"

    if re.search(r"\d{4}-\d{2}-\d{2}", sample_text):
        return "iso_date_like"

    if re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", sample_text):
        return "ambiguous_date_like"

    if non_null.str.isnumeric().all():
        return "numeric"

    return "text"


def summarize_column(series):
    non_null = series.dropna()

    null_pct = round(series.isna().mean() * 100, 2)

    unique_pct = (
        round((non_null.nunique() / len(non_null)) * 100, 2)
        if len(non_null) > 0
        else 0
    )

    samples = (
        non_null.astype(str)
        .drop_duplicates()
        .head(MAX_SAMPLE_VALUES)
        .tolist()
    )

    return {
        "dtype": str(series.dtype),
        "null_pct": null_pct,
        "unique_pct": unique_pct,
        "sample_values": samples,
        "pattern_hint": infer_pattern(series),
    }


def profile_dataframe(df):
    profile = {
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": {},
    }

    for column in df.columns:
        profile["columns"][column] = summarize_column(df[column])

    return profile


def load_source_file(file_path):
    if file_path.endswith(".csv"):
        return pd.read_csv(file_path)

    if file_path.endswith(".xlsx"):
        return pd.read_excel(file_path)

    raise ValueError("Unsupported file format. Use CSV or XLSX.")


def profile_source(file_path):
    df = load_source_file(file_path)
    profile = profile_dataframe(df)
    return df, profile