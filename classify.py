# classify.py - simple TF-IDF + LogisticRegression doc classifier
import os
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import joblib

DATA_FILE = os.path.join("data", "doc_labels.csv")
MODEL_FILE = "doc_classifier.joblib"

def train_if_data_exists():
    if not os.path.exists(DATA_FILE):
        print("No labeled data found at", DATA_FILE)
        return
    df = pd.read_csv(DATA_FILE)
    X = df.text.values
    y = df.label.values
    X_train, X_test, y_train, y_test = train_test_split(X,y,test_size=0.2,random_state=42,stratify=y)
    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1,2), max_features=8000)),
        ("clf", LogisticRegression(max_iter=1000))
    ])
    pipeline.fit(X_train, y_train)
    preds = pipeline.predict(X_test)
    print(classification_report(y_test,preds,zero_division=0))
    joblib.dump(pipeline, MODEL_FILE)
    print("Saved classifier to", MODEL_FILE)

if __name__ == "__main__":
    train_if_data_exists()
